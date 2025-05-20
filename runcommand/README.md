# Installing the CrowdStrike Falcon Sensor on OCI Instances using OCI Run Command

This guide provides instructions for deploying the CrowdStrike Falcon Sensor to Oracle Cloud Infrastructure (OCI) instances using OCI Run Command. Run Command allows you to execute commands remotely on your OCI instances, making it an efficient method for deploying and managing the Falcon Sensor across your cloud environment.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Falcon API Permissions](#falcon-api-permissions)
- [Policy Configuration](#policy-configuration)
- [Configure the Vault and Secrets](#configure-the-vault-and-secrets)
- [Upload the Installation Scripts](#upload-the-installation-scripts)
- [Run Command](#run-command)
- []()

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
  > Required when using the `FALCON_SENSOR_UPDATE_POLICY` environment variable to specify a sensor update policy.


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

## Run Command

Once you have completed the setup steps above, you can use OCI Run Command to deploy the Falcon Sensor to your instances. 
To deploy the Falcon Sensor:

1. Navigate to the OCI Console
2. Select `Compute` > `Instances`
3. Select the instance where you want to install the sensor
4. Click on `Management` and scroll down to `Run command`. Click on `Create command`
5. Select `Import from an Object Storage bucket`
6. In the `Bucket in compartment` field, select your bucket containing the installation scripts 
7. For Linux instances, enter `install.sh` for the `Object name`, and for Windows instances, enter `install.cmd` for the `Object name`
8. Click "Create command" to execute the installation script on the selected instance

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
