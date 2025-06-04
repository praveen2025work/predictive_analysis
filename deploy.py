from azure.identity import DefaultAzureCredential
from azure.ai.ml import MLClient
from azure.ai.ml.entities import ManagedOnlineEndpoint, ManagedOnlineDeployment
from azure.ai.ml.entities import Model as MLModel, Environment
import uuid
from azure.mgmt.resource import ResourceManagementClient

# Set these values
subscription_id = "9570e3d5-306e-462c-a985-1e469e85a0c8"
resource_group = "test"
workspace = "predictivesapui"

# ✅ Test authentication first
try:
    credential = DefaultAzureCredential()
    # Test authentication - USE THE ACTUAL SUBSCRIPTION ID
    resource_client = ResourceManagementClient(credential, subscription_id)
    print("✅ Authentication successful")
except Exception as e:
    print(f"❌ Authentication failed: {e}")
    exit(1)

# ✅ Test ML Client connection
try:
    ml_client = MLClient(
        credential=credential,
        subscription_id=subscription_id,
        resource_group_name=resource_group,
        workspace_name=workspace
    )
    # Test the connection by getting workspace info
    workspace_info = ml_client.workspaces.get()
    print(f"✅ Connected to ML workspace: {workspace_info.name}")
except Exception as e:
    print(f"❌ ML Client connection failed: {e}")
    print("Make sure your workspace exists and you have proper permissions")
    exit(1)

# ✅ Register the model
try:
    model = MLModel(
        path="balance_model.pkl",
        name="balance-predictor",
        description="Linear regression model for balance prediction",
        type="custom_model",
    )
    registered_model = ml_client.models.create_or_update(model)
    print(f"✅ Model registered: {registered_model.name}")
except Exception as e:
    print(f"❌ Model registration failed: {e}")
    exit(1)

# ✅ Create a unique endpoint name
unique_id = str(uuid.uuid4())[:8]
endpoint_name = f"balance-predictor-{unique_id}"
print(f"🆕 Creating new endpoint: {endpoint_name}")

# ✅ Create a new endpoint with explicit configuration
try:
    endpoint = ManagedOnlineEndpoint(
        name=endpoint_name,
        description="Endpoint for predicting balances",
        auth_mode="key",
        # Add explicit tags to help with tracking
        tags={"project": "balance-predictor", "environment": "test"}
    )
    
    print(f"🔄 Creating endpoint (this may take 5-10 minutes)...")
    # Use create_or_update with explicit wait and timeout
    poller = ml_client.begin_create_or_update(endpoint)
    result = poller.result(timeout=600)  # 10 minute timeout
    print(f"✅ Endpoint created: {result.name}")
except Exception as e:
    print(f"❌ Endpoint creation failed: {e}")
    print("Full error details:", str(e))
    exit(1)

# ✅ Create an environment
try:
    env = Environment(
        image="mcr.microsoft.com/azureml/minimal-ubuntu20.04-py38-cpu-inference:latest",
        conda_file="predictive-model/environment.yml",
        name="balance-env",
        description="Env for balance predictor",
    )
    print("✅ Environment defined")
except Exception as e:
    print(f"❌ Environment creation failed: {e}")
    exit(1)

# ✅ Create a deployment
try:
    deployment = ManagedOnlineDeployment(
        name="blue",
        endpoint_name=endpoint.name,
        model=registered_model.id,
        environment=env,
        code_path="./predictive-model",  # folder with score.py
        scoring_script="score.py",
        instance_type="Standard_B1s",
        instance_count=1
    )
    print("🔄 Creating deployment (this may take several minutes)...")
    ml_client.begin_create_or_update(deployment).wait()
    print("✅ Deployment created and ready")
except Exception as e:
    print(f"❌ Deployment creation failed: {e}")
    exit(1)

# ✅ Set traffic to the deployment
try:
    ml_client.online_endpoints.begin_update(
        endpoint_name=endpoint.name,
        traffic={"blue": 100}
    ).wait()
    print("✅ Traffic routed to deployment")
except Exception as e:
    print(f"❌ Traffic routing failed: {e}")
    exit(1)

# ✅ Get scoring URI and keys
try:
    endpoint = ml_client.online_endpoints.get(endpoint.name)
    print("🔗 Scoring URI:", endpoint.scoring_uri)
    
    keys = ml_client.online_endpoints.list_keys(endpoint.name)
    print("🔑 Primary Key:", keys.primary_key)
    print("✅ Deployment completed successfully!")
except Exception as e:
    print(f"❌ Failed to get endpoint details: {e}")