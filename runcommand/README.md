# Installing the CrowdStrike Falcon Sensor on OCI Instances using OCI Run Command

This guide provides instructions for deploying the CrowdStrike Falcon Sensor to Oracle Cloud Infrastructure (OCI) instances using OCI Run Command. Run Command allows you to execute commands remotely on your OCI instances, making it an efficient method for deploying and managing the Falcon Sensor across your cloud environment.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Falcon API Permissions](#falcon-api-permissions)
- [Policy Configuration](#policy-configuration)
- [Configure the Vault and Secrets](#configure-the-vault-and-secrets)
- [Upload the Installation Scripts](#upload-the-installation-scripts)
- [Deployment Methods](#deployment-methods)
  - [Manual Deployment via OCI Console](#manual-deployment-via-oci-console)
  - [Automated Deployment via Python Script](#automated-deployment-via-python-script)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- An active CrowdStrike Falcon subscription
- Access to Oracle Cloud Infrastructure (OCI) Console
- OCI instances with Compute Instance Run Command plugin enabled
- A storage bucket that allows read access with a url accessible from the OCI instances
- A vault in OCI to securely store your CrowdStrike API credentials

> [!IMPORTANT]
> The OCI Run Command must be configured to run with sudo or Administrator privileges to install the Falcon Sensor. See [OCI documentation on Run Command](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/runningcommands.htm) for detailed instructions on proper configuration.

## Falcon API Permissions

API clients are granted one or more API scopes. Scopes allow access to specific CrowdStrike APIs and describe the actions that an API client can perform.

Ensure the following API scopes are enabled:

- **Sensor Download** [read]
  > Required for downloading the Falcon Sensor installation package.

- **Installation Tokens** [read]
  > Required if your environment enforces installation tokens for Falcon Sensor installation.

- **Sensor update policies** [read]
  > Required to specify a sensor update policy.


## Policy Configuration

Before using OCI Run Command to deploy the CrowdStrike Falcon Sensor, ensure you have the appropriate policies in place that allow access to read vaults and storage buckets as well as the ability to run commands on OCI instances.

### Tenant Policy Configuration

#### Create a dynamic group

1. Navigate to Identity & Security > Dynamic Groups in the OCI Console

2. Create a dynamic group with the following rule replacing `<your_tenancy_ocid>` with your actual tenancy OCID:

   ```
   ALL {instance.compartment.id = '<your_tenancy_ocid>'}
   ```

> [!NOTE]
> You might have to wait 30 mins before the dynamic group to be applies to the instance

#### Create a policy for your dynamic group

1. Navigate to Identity & Security > Policies in the OCI Console

2. Create a policy with the following statements, replacing:
   - `<your-dynamic-group-name>` with your actual dynamic group name
   - `<your_bucket_name>` with your actual bucket name
   - `<your-vault-id>` with your actual vault ID

   ```
   Allow group <your-dynamic-group-name> to manage instance-agent-command-family in tenancy
   Allow dynamic-group <your-dynamic-group-name> to use instance-agent-command-execution-family in tenancy
   Allow dynamic-group <your-dynamic-group-name> to read objects in tenancy where all {target.bucket.name = '<your_bucket_name>'}
   Allow dynamic-group <your-dynamic-group-name> to manage objects in tenancy where all {target.bucket.name = '<your_bucket_name>'}
   Allow dynamic-group <your-dynamic-group-name> to read secret-family in tenancy where target.vault.id = '<your-vault-id>'
   Allow dynamic-group <your-dynamic-group-name> to inspect vaults in tenancy
   ```

## Configure the Vault and Secrets

1. Under Identity & Security > Vault in the OCI Console, create a vault if one does not already exist, and add the following secrets, manually setting the secret values:

   - **FALCON_CLIENT_ID**: Your Falcon API OAuth Client ID
   - **FALCON_CLIENT_SECRET**: Your Falcon API OAuth Client Secret

   You can optionally configure more installation settings by adding additional secrets to the vault:

   - **FALCON_CID**: Your Falcon Customer ID (CID)
   - **FALCON_CLOUD**: Your Falcon Cloud region (e.g. us-1, us-2, eu-1). Default is autodiscover
   - **FALCON_SENSOR_UPDATE_POLICY**: The Falcon Sensor Update Policy name to assign to the sensor
   - **FALCON_TAGS**: Optional tags to apply to the sensor during installation

## Upload the Installation Scripts

1. Update configuration of the following parameters in the [install.sh](install.sh) and [install.cmd](install.cmd) installation wrapper scripts:

- **OCID**: Your Oracle Cloud Identifier (tenancy OCID) e.g. ocid1.tenancy.oc1..asdf79as8dfka983aksdjhf
- **VAULT_NAME**: The name of your OCI vault where secrets are stored e.g. falcon-run-command-vault
- **BUCKET_URL**: The URL to your Object Storage bucket where the Falcon Sensor packages are stored e.g. https://objectstorage.region.oraclecloud.com/p/your-preauthenticated-request-token/n/your-namespace/b/your-bucket-name/o/

2. Upload the installation wrapper scripts to your Object Storage bucket. This should be the same bucket that the install scripts are referencing via the `BUCKET_URL` parameter.

3. Upload the non-archived Windows and Linux installer binaries from https://github.com/CrowdStrike/falcon-installer/releases/latest to your Object Storage bucket.

## Deployment Methods

You can deploy the Falcon Sensor using either manual deployment through the OCI Console or automated deployment using the provided Python script.

### Manual Deployment via OCI Console

To deploy the Falcon Sensor manually:

1. Navigate to the OCI Console
2. Select `Compute` > `Instances`
3. Select the instance where you want to install the sensor
4. Click on `Management` and scroll down to `Run command`. Click on `Create command`
5. Select `Import from an Object Storage bucket`
6. In the `Bucket in compartment` field, select your bucket containing the installation scripts
7. For Linux instances, enter `install.sh` for the `Object name`, and for Windows instances, enter `install.cmd` for the `Object name`
8. Click "Create command" to execute the installation script on the selected instance

### Automated Deployment via Python Script

For large-scale deployments or automation, use the `falcon_oci_deploy.py` script to deploy the Falcon Sensor across multiple instances automatically.

#### Prerequisites for Automated Deployment

1. **Python Dependencies**: Install the required Python packages:
   ```bash
   pip install oci
   ```

2. **OCI Configuration**: Ensure your OCI CLI is configured with appropriate credentials:
   ```bash
   oci setup config
   ```
   Or manually create `~/.oci/config` with your OCI credentials.


> [!NOTE]
> The existing dynamic group policies are sufficient for the target instances to execute the installation scripts. No additional policies are required beyond what's already configured in the [Policy Configuration](#policy-configuration) section.

#### Using the Automated Deployment Script

The `falcon_oci_deploy.py` script automatically:
- Discovers all running instances across your tenancy
- Detects the operating system (Linux/Windows) for each instance
- Deploys the appropriate installation script based on OS type
- Provides real-time monitoring of deployment status
- Handles rate limiting and batch processing for large deployments

#### Basic Usage

```shell
# Deploy to all instances in your tenancy
python falcon_oci_deploy.py --bucket-name your-bucket-name

# Deploy to specific compartments only
python falcon_oci_deploy.py --bucket-name your-bucket-name --compartments ocid1.compartment.oc1..example1 ocid1.compartment.oc1..example2

# Deploy to a specific instance by name
python falcon_oci_deploy.py --bucket-name your-bucket-name --instance-name "my-web-server"

# Use custom script names
python falcon_oci_deploy.py --bucket-name your-bucket-name --linux-script custom-install.sh --windows-script custom-install.cmd

# Run with monitoring and logging
python falcon_oci_deploy.py --bucket-name your-bucket-name --log --log-interval 60 --log-max-wait 3600

# Run in batch mode (non-interactive)
python falcon_oci_deploy.py --bucket-name your-bucket-name --batch
```

#### Command Line Options

- `--bucket-name`: (Required) OCI Object Storage bucket name containing installation scripts
- `--linux-script`: Linux installation script name (default: `install.sh`)
- `--windows-script`: Windows installation script name (default: `install.cmd`)
- `--compartments`: Specific compartment IDs to target (optional, defaults to all compartments)
- `--instance-name`: Deploy to a specific instance by name (optional)
- `--config-file`: OCI config file path (default: `~/.oci/config`)
- `--profile`: OCI config profile (default: `DEFAULT`)
- `--log`: Enable deployment status monitoring after execution
- `--log-interval`: Status check interval in seconds (default: 30)
- `--log-max-wait`: Maximum wait time for monitoring in seconds (default: 1800)
- `--batch`: Run in non-interactive mode


#### Features

- **OS Auto-Detection**: Automatically detects Linux vs Windows instances
- **Rate Limiting**: Respects OCI API rate limits (configurable, default 800 RPS)
- **Batch Processing**: Processes instances in configurable batches (default 50)
- **Concurrent Execution**: Uses threading for faster deployment
- **Real-time Monitoring**: Optional monitoring of deployment status
- **Error Handling**: Comprehensive error handling and reporting
- **Flexible Targeting**: Deploy to all instances, specific compartments, or individual instances

## Troubleshooting

If you encounter issues during installation, check the following:

1. Verify that all required secrets are properly set in the vault
2. The dynamic group is configured to access the instances properly
3. The policy has the correct settings to access the required resources
4. Ensure that Compute Instance Run Command plugin:
   - Is enabled on your instance
   - Has the required permissions to access the Object Storage bucket
   - Has sudo permissions with nopasswd for Linux instances and administrative privileges for Windows instances
5. Confirm that the Object Storage bucket contains the correct installer binaries and installation wrapper scripts
6. Check the Oracle Cloud Agent logs for any failures related to the run command.
7. Check the installation logs:
   - For Linux: `/tmp/falcon/falcon-installer.log`
   - For Windows: `C:\Windows\Temp\falcon-installer.log`

### Automated Deployment Troubleshooting

For issues with the `falcon_oci_deploy.py` script:

1. **Authentication Issues**: Verify your OCI configuration:
   ```bash
   oci iam user get --user-id $(oci iam user list --query 'data[0].id' --raw-output)
   ```

2. **Permission Issues**: Ensure your user has the required policies listed above

3. **Rate Limiting**: If you encounter rate limiting errors, the script will automatically retry with backoff

4. **Instance Agent Issues**: Verify that the Oracle Cloud Agent is running on target instances:
   ```bash
   # On Linux instances
   sudo systemctl status oracle-cloud-agent

   # On Windows instances (PowerShell as Administrator)
   Get-Service "Oracle Cloud Agent"
   ```

5. **Script Execution**: Check the run command execution logs in the OCI Console under Compute > Instances > [Instance] > Management > Run command
