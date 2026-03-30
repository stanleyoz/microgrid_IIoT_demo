#  SETUP 

import google.auth
try:
        credentials, project_id = google.auth.default()
        print("Credentials type: {type(credentials)}")
         print("Project ID: {project_id}")                                                                                    
        if credentials.service_account_email:                                                                                    
            print("Service Account Email: {credentials.service_account_email}")                                               
        else:                                                                                                                    
            print("Not using a service account for authentication.")
except Exception as e:
        print("Could not retrieve default credentials: {e}")

File /opt/conda/lib/python3.10/site-packages/google/cloud/storage/client.py:774, in Client._post_resource(self, path, data, query_params, headers, timeout, retry, _target_object)
# ── CELL 2 ──────────────────────────────────────────────────────────────────
query_full = """
SELECT
site_id, timestamp,
battery_v, battery_soc, battery_current, battery_temp,
ac_input_v, ac_output_v, ac_output_i,
ac_input_power, ac_output_power,
solar_w, load_w, inverter_state, inverter_temp,
fault_code, power_balance_w
FROM `microgrid-demo.microgrid_db.microgrid_telemetry`
ORDER BY site_id, timestamp ASC
"""
df_train = client.query(query_full).to_dataframe()
print(f"Fetched {len(df_train):,} rows | {df_train['site_id'].nunique()} sites")
print(f"Date range: {df_train['timestamp'].min()} -> {df_train['timestamp'].max()}")

# ── CELL 3 ──────────────────────────────────────────────────────────────────
import numpy as np

df_train['timestamp'] = pd.to_datetime(df_train['timestamp'])
df_train = df_train.sort_values(['site_id', 'timestamp']).reset_index(drop=True)

df_train['battery_v_norm'] = df_train['battery_v'] / 24.0

df_train['efficiency_ratio'] = (
    df_train['ac_output_power'] /
    (df_train['ac_input_power'] + df_train['solar_w']).replace(0, np.nan)
)

df_train['prev_soc'] = df_train.groupby('site_id')['battery_soc'].shift(1)
df_train['prev_ts'] = df_train.groupby('site_id')['timestamp'].shift(1)
dt_seconds = (df_train['timestamp'] - df_train['prev_ts']).dt.total_seconds()
df_train['soc_rate_per_min'] = (
    (df_train['battery_soc'] - df_train['prev_soc']) / dt_seconds * 60
)

df_train['hour_bucket'] = df_train['timestamp'].dt.floor('h')
transitions = (
    df_train.groupby(['site_id', 'hour_bucket'])['inverter_state']
    .transform(lambda x: (x != x.shift()).sum())
)
df_train['mode_transitions_per_hour'] = transitions

df_feat = df_train.dropna(subset=['soc_rate_per_min', 'efficiency_ratio']).copy()
print(f"Training rows after feature engineering: {len(df_feat):,}")
print(df_feat[['battery_v_norm','efficiency_ratio','soc_rate_per_min','mode_transitions_per_hour']].describe())

# ── CELL 4 ──────────────────────────────────────────────────────────────────
from sklearn.preprocessing import StandardScaler

FEATURE_COLS = [
    'battery_v', 'battery_soc', 'battery_current', 'battery_temp',
    'ac_input_v', 'ac_output_v', 'ac_input_power', 'ac_output_power',
    'solar_w', 'load_w', 'inverter_temp', 'power_balance_w',
    'battery_v_norm', 'efficiency_ratio', 'soc_rate_per_min',
    'mode_transitions_per_hour'
]

X = df_feat[FEATURE_COLS].copy()
X['efficiency_ratio'] = X['efficiency_ratio'].clip(-5, 5)
X['soc_rate_per_min'] = X['soc_rate_per_min'].clip(-10, 10)

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
print(f"Feature matrix shape: {X_scaled.shape}")

# ── CELL 5 ──────────────────────────────────────────────────────────────────
from sklearn.ensemble import IsolationForest

model = IsolationForest(
    n_estimators=200,
    contamination=0.05,
    random_state=42,
    n_jobs=-1
)
model.fit(X_scaled)
print("Model trained.")

df_feat['anomaly_label'] = model.predict(X_scaled)
df_feat['anomaly_score'] = model.score_samples(X_scaled)

n_anomalies = (df_feat['anomaly_label'] == -1).sum()
print(f"Flagged anomalies: {n_anomalies:,} / {len(df_feat):,} ({n_anomalies/len(df_feat)*100:.1f}%)")

# ── CELL 6 ──────────────────────────────────────────────────────────────────
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(14, 4))

axes[0].hist(df_feat['anomaly_score'], bins=60, color='steelblue', edgecolor='white')
axes[0].axvline(
    df_feat[df_feat['anomaly_label'] == -1]['anomaly_score'].max(),
    color='red', linestyle='--', label='anomaly threshold'
)
axes[0].set_title('Anomaly Score Distribution')
axes[0].set_xlabel('Score (lower = more anomalous)')
axes[0].legend()

anomaly_counts = df_feat[df_feat['anomaly_label'] == -1].groupby('site_id').size()
anomaly_counts.plot(kind='bar', ax=axes[1], color='tomato')
axes[1].set_title('Anomaly Count per Site')
axes[1].set_xlabel('')

plt.tight_layout()
plt.show()

cols_show = ['site_id', 'timestamp', 'battery_soc', 'solar_w', 'load_w', 'power_balance_w', 'anomaly_score']
print("\nTop 10 most anomalous readings:")
print(df_feat.nsmallest(10, 'anomaly_score')[cols_show].to_string(index=False))

# ── CELL 7 ──────────────────────────────────────────────────────────────────
import joblib, os, json
from google.cloud import storage
from datetime import date

MODEL_DATE = date.today().isoformat()
BUCKET_NAME = 'microgrid-ml-artefacts'
LOCAL_DIR = f'/tmp/model/{MODEL_DATE}'

os.makedirs(LOCAL_DIR, exist_ok=True)
joblib.dump(model, f'{LOCAL_DIR}/isolation_forest.joblib')
joblib.dump(scaler, f'{LOCAL_DIR}/scaler.joblib')

metadata = {
    'trained_on': MODEL_DATE,
    'n_training_rows': len(df_feat),
    'n_features': len(FEATURE_COLS),
    'feature_cols': FEATURE_COLS,
    'contamination': 0.05,
    'n_estimators': 200,
    'n_anomalies_flagged': int(n_anomalies),
    'sites': sorted(df_feat['site_id'].unique().tolist())
}
with open(f'{LOCAL_DIR}/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

storage_client = storage.Client(project='microgrid-demo')
bucket = storage_client.bucket(BUCKET_NAME)

files = ['isolation_forest.joblib', 'scaler.joblib', 'metadata.json']
for fname in files:
    bucket.blob(f'models/{MODEL_DATE}/{fname}').upload_from_filename(f'{LOCAL_DIR}/{fname}')
    print(f"Uploaded gs://{BUCKET_NAME}/models/{MODEL_DATE}/{fname}")
