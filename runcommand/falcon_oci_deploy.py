#!/usr/bin/env python3
"""
OCI Run Command Script for CrowdStrike Falcon Sensor Installation
Pure OCI SDK implementation with OS auto-discovery, Object Storage import, and RPS throttling
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
import argparse
from datetime import datetime
import json

import oci
import oci.compute_instance_agent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FalconRunCommandManager:
    """Manages deployment of CrowdStrike Falcon sensor to OCI instances using Run Command."""
    def __init__(self, config_file: str = "~/.oci/config", profile: str = "DEFAULT"):
        """Initialize OCI clients with rate limiting"""
        try:
            self.config = oci.config.from_file(config_file, profile)

            # Validate configuration
            oci.config.validate_config(self.config)

            # Initialize clients (authentication will be tested on first API call)
            self.compute_client = oci.compute_instance_agent.ComputeInstanceAgentClient(self.config)
            self.core_client = oci.core.ComputeClient(self.config)  # For instance listing
            self.object_storage_client = oci.object_storage.ObjectStorageClient(self.config)
            self.identity_client = oci.identity.IdentityClient(self.config)

            # Rate limiting configuration
            self.max_rps = 800  # Stay under 1000 RPS limit with buffer
            self.request_interval = 1.0 / self.max_rps  # Time between requests
            self.last_request_time = 0

            # Batch configuration
            self.batch_size = 50  # Process instances in batches
            self.max_workers = 10  # Concurrent threads

            # Get namespace (this will test authentication naturally)
            self.namespace = self._get_namespace()
            logger.info("✅ OCI clients initialized successfully")

        except oci.exceptions.ConfigFileNotFound as e:
            logger.error("OCI config file not found: %s", e)
            logger.error("Please ensure ~/.oci/config exists and is properly configured")
            raise
        except oci.exceptions.InvalidConfig as e:
            logger.error("Invalid OCI configuration: %s", e)
            logger.error("Please check your ~/.oci/config file format")
            raise
        except oci.exceptions.ServiceError as e:
            if e.status == 401:
                logger.error("Authentication failed: %s", e.message)
                logger.error("Please check:")
                logger.error("  1. Your user OCID is correct")
                logger.error("  2. Your private key file exists and has correct permissions")
                logger.error("  3. Your fingerprint matches your public key")
                logger.error("  4. Your user has the required permissions")
            elif e.status == 404:
                logger.error("Resource not found or not authorized: %s", e.message)
                logger.error("Please check your user permissions and resource access")
            else:
                logger.error("OCI service error: %s", e)
            raise
        except Exception as e:
            logger.error("Failed to initialize OCI clients: %s", e)
            raise


    def _rate_limit(self):
        """Enforce rate limiting between API calls"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.request_interval:
            sleep_time = self.request_interval - time_since_last
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _get_namespace(self) -> str:
        """Get the Object Storage namespace"""
        try:
            self._rate_limit()
            namespace = self.object_storage_client.get_namespace().data
            logger.info("Object Storage namespace: %s", namespace)
            return namespace
        except oci.exceptions.ServiceError as e:
            if e.status == 401:
                logger.error("Authentication failed when getting namespace")
                logger.error("Your user may not have permissions to access Object Storage")
                logger.error("Required policy: 'Allow user <username> to use object-storage-namespaces in tenancy'")
            else:
                logger.error("Error getting namespace: %s", e)
            raise
        except Exception as e:
            logger.error("Error getting namespace: %s", e)
            raise

    def get_instance_os_type(self, instance_id: str) -> str:
        """Determine if instance is Linux or Windows based on platform details"""
        try:
            self._rate_limit()

            # Get instance details using core client
            instance = self.core_client.get_instance(instance_id).data

            # Check the image details to determine OS
            if hasattr(instance, 'source_details') and instance.source_details:
                if hasattr(instance.source_details, 'image_id'):
                    image_id = instance.source_details.image_id

                    # Get image details
                    self._rate_limit()
                    image = self.core_client.get_image(image_id).data

                    # Check operating system from image
                    if hasattr(image, 'operating_system'):
                        os_name = image.operating_system.lower()
                        if 'windows' in os_name:
                            return 'windows'
                        elif any(linux_os in os_name for linux_os in ['linux', 'ubuntu', 'centos', 'rhel', 'oracle', 'debian']):
                            return 'linux'

                    # Check display name as fallback
                    if hasattr(image, 'display_name'):
                        display_name = image.display_name.lower()
                        if 'windows' in display_name:
                            return 'windows'
                        elif any(linux_os in display_name for linux_os in ['linux', 'ubuntu', 'centos', 'rhel', 'oracle', 'debian']):
                            return 'linux'

            # Fallback: check instance shape (some shapes are Windows-specific)
            shape = instance.shape.lower()
            if 'windows' in shape:
                return 'windows'

            # Default to Linux if we can't determine
            logger.warning("Could not determine OS for instance %s, defaulting to Linux", instance_id)
            return 'linux'

        # pylint: disable=broad-except
        except Exception as e:
            logger.error("Error determining OS for instance %s: %s", instance_id, e)
            return 'linux'  # Default to Linux

    def get_all_instances_with_os(self, compartment_ids: List[str] = None, instance_name: str = None) -> List[Dict]:
        """Get all instances with OS type detection"""
        all_instances = []

        if not compartment_ids:
            # Get all compartments in tenancy
            compartment_ids = self._get_all_compartments()

        logger.info("Scanning %d compartments for instances...", len(compartment_ids))

        for compartment_id in compartment_ids:
            try:
                self._rate_limit()

                instances = self.core_client.list_instances(
                    compartment_id=compartment_id,
                    lifecycle_state="RUNNING"  # Only running instances
                ).data

                for instance in instances:
                    # Detect OS type
                    os_type = self.get_instance_os_type(instance.id)
                    all_instances.append({
                        'id': instance.id,
                        'display_name': instance.display_name,
                        'compartment_id': compartment_id,
                        'shape': instance.shape,
                        'lifecycle_state': instance.lifecycle_state,
                        'os_type': os_type
                    })

                    if instance_name is not None and instance.display_name.lower() == instance_name.lower():
                        break

                logger.info("Found %d running instances in compartment %s", len(instances), compartment_id)

            # pylint: disable=broad-except
            except Exception as e:
                logger.error("Error listing instances in compartment %s: %s", compartment_id, e)
                continue

        # Summary by OS
        linux_count = sum(1 for i in all_instances if i['os_type'] == 'linux')
        windows_count = sum(1 for i in all_instances if i['os_type'] == 'windows')

        logger.info("Total instances found: %d (Linux: %d, Windows: %d)", len(all_instances), linux_count, windows_count)
        return all_instances

    def _get_all_compartments(self) -> List[str]:
        """Get all compartment IDs in the tenancy"""
        compartments = []

        try:
            self._rate_limit()
            tenancy_id = self.config['tenancy']

            # Add root compartment
            compartments.append(tenancy_id)

            # Get all sub-compartments
            all_compartments = self.identity_client.list_compartments(
                compartment_id=tenancy_id,
                compartment_id_in_subtree=True
            ).data

            for comp in all_compartments:
                if comp.lifecycle_state == "ACTIVE":
                    compartments.append(comp.id)

        # pylint: disable=broad-except
        except Exception as e:
            logger.error("Error getting compartments: %s", e)

        return compartments

    def verify_bucket_access(self, bucket_name: str, linux_script: str, windows_script: str) -> Dict[str, bool]:
        """Verify that the bucket and both scripts exist"""
        results = {'linux': False, 'windows': False}

        for script_type, script_name in [('linux', linux_script), ('windows', windows_script)]:
            try:
                self._rate_limit()

                self.object_storage_client.head_object(
                    namespace_name=self.namespace,
                    bucket_name=bucket_name,
                    object_name=script_name
                )

                results[script_type] = True
                logger.info("✅ Verified access to %s/%s", bucket_name, script_name)

            # pylint: disable=broad-except
            except Exception as e:
                logger.error("❌ Cannot access %s/%s: %s", bucket_name, script_name, e)
                results[script_type] = False

        return results

    def create_run_command_from_storage(self, instance_id: str, bucket_name: str,
                                  script_name: str, compartment_id: str,
                                  instance_name: str, os_type: str = None) -> Optional[str]:
        """Create run command that imports directly from Object Storage"""
        try:
            self._rate_limit()

            logger.info("Creating command for %s (%s) using bucket: %s/%s",
                   instance_name, os_type or "unknown", bucket_name, script_name)

            # Build the Object Storage URI
            source_uri = f"https://objectstorage.{self.config['region']}.oraclecloud.com/n/{self.namespace}/b/{bucket_name}/o/{script_name}"

            # Verify the URI looks correct
            if not script_name or script_name.strip() == "":
                logger.error("❌ Script name is empty!")
                return None

            if source_uri.endswith("/o/"):
                logger.error("❌ Source URI is missing script name: %s", source_uri)
                return None

            # Use the correct content structure - source details go in the content
            source_details = oci.compute_instance_agent.models.InstanceAgentCommandSourceViaObjectStorageTupleDetails(
                source_type="OBJECT_STORAGE_TUPLE",
                namespace_name=self.namespace,
                bucket_name=bucket_name,
                object_name=script_name
            )

            # Create content with the source details
            content = oci.compute_instance_agent.models.InstanceAgentCommandContent(
                source=source_details
            )

            create_command_details = oci.compute_instance_agent.models.CreateInstanceAgentCommandDetails(
                compartment_id=compartment_id,
                display_name=f"CrowdStrike-Falcon-Install-{instance_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                target=oci.compute_instance_agent.models.InstanceAgentCommandTarget(
                    instance_id=instance_id
                ),
                content=content,
                execution_time_out_in_seconds=3600  # 1 hour timeout
            )

            response = self.compute_client.create_instance_agent_command(
                create_instance_agent_command_details=create_command_details
            )

            command_id = response.data.id
            os_info = f" ({os_type})" if os_type else ""
            logger.info("✅ Run command created for instance %s%s (%s)", instance_name, os_info, instance_id)
            logger.info("   Command ID: %s", command_id)
            logger.info("   Script: %s", script_name)

            return command_id

        # pylint: disable=broad-except
        except Exception as e:
            logger.error("❌ Error creating run command for instance %s: %s", instance_id, e)
            return None

    def check_command_status(self, command_id: str, instance_id: str) -> Dict:
        """Check the status of a run command by looking at execution status"""
        try:
            self._rate_limit()

            # First get the command to check if it's canceled
            command_response = self._retry_api_call(
                lambda: self.compute_client.get_instance_agent_command(instance_agent_command_id=command_id)
            )
            command = command_response.data

            if command.is_canceled:
                return {
                    'command_id': command_id,
                    'instance_id': instance_id,
                    'lifecycle_state': 'CANCELED',
                    'time_created': command.time_created,
                    'time_updated': command.time_updated
                }

            # Get the actual execution status
            try:
                execution_response = self._retry_api_call(
                    lambda: self.compute_client.get_instance_agent_command_execution(
                        instance_agent_command_id=command_id, instance_id=instance_id
                    )
                )
                execution = execution_response.data

                # Debug: Show execution attributes
                available_attrs = [attr for attr in dir(execution) if not attr.startswith('_')]
                logger.debug("Execution attributes: %s", available_attrs)

                # Look for lifecycle state in execution
                lifecycle_state = getattr(execution, 'lifecycle_state', None)
                if not lifecycle_state:
                    # Try other possible attributes
                    for attr in ['status', 'state', 'execution_state']:
                        if hasattr(execution, attr):
                            lifecycle_state = getattr(execution, attr)
                            break

                if not lifecycle_state:
                    # Try to find exit code with different attribute names
                    exit_code = None
                    for attr_name in ['exit_code', 'return_code', 'status_code', 'result_code']:
                        if hasattr(execution, attr_name):
                            exit_code = getattr(execution, attr_name)
                            break

                    if exit_code is not None:
                        lifecycle_state = 'SUCCEEDED' if exit_code == 0 else 'FAILED'
                    else:
                        lifecycle_state = 'IN_PROGRESS'

                return {
                    'command_id': command_id,
                    'instance_id': instance_id,
                    'lifecycle_state': lifecycle_state,
                    'exit_code': getattr(execution, 'exit_code', None),
                    'time_created': command.time_created,
                    'time_updated': command.time_updated,
                    'content': getattr(execution, 'content', None)
                }

            except oci.exceptions.ServiceError as e:
                if e.status == 404:
                    # Execution not found yet - command is still being processed
                    return {
                        'command_id': command_id,
                        'instance_id': instance_id,
                        'lifecycle_state': 'IN_PROGRESS',
                        'time_created': command.time_created,
                        'time_updated': command.time_updated
                    }
                else:
                    raise

        # pylint: disable=broad-except
        except Exception as e:
            logger.error("Error checking command status for %s: %s", command_id, e)
            return None


    def _retry_api_call(self, api_call, max_retries=3):
        """Simple retry wrapper for API calls"""
        for attempt in range(max_retries):
            try:
                return api_call()
            except Exception as e:
                if ("Connection aborted" in str(e) or "RemoteDisconnected" in str(e)) and attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 2)  # 2s, 4s delays
                    continue
                raise

    def get_command_output(self, command_id: str, instance_id: str) -> Dict:
        """Get the output of a completed command"""
        try:
            self._rate_limit()

            response = self.compute_client.get_instance_agent_command_execution(
                instance_agent_command_id=command_id,
                instance_id=instance_id
            )
            execution = response.data
            content = execution.content

            exit_code = None
            output_text = ""
            error_message = ""

            # Try to get exit code from content attributes
            if hasattr(content, 'exit_code'):
                exit_code = content.exit_code

            # Try to get output text
            if hasattr(content, 'text'):
                output_text = content.text or ""

            # Parse the message field which contains JSON with error details
            if hasattr(content, 'message') and content.message:
                try:
                    message_data = json.loads(content.message)

                    # Get exit code if not already found
                    if exit_code is None and 'exit_code' in message_data:
                        exit_code = message_data['exit_code']

                    # Extract error messages
                    if 'errs' in message_data and message_data['errs']:
                        error_message = '\n'.join(message_data['errs'])
                    elif 'message' in message_data:
                        error_message = message_data['message']

                except (json.JSONDecodeError, TypeError) as e:
                    # If JSON parsing fails, use the raw message
                    error_message = str(content.message)
                    logger.debug("Failed to parse JSON message: %s", e)

            # If still no error message, try other attributes
            if not error_message:
                for attr in ['error', 'stderr', 'error_output']:
                    if hasattr(content, attr):
                        attr_value = getattr(content, attr)
                        if attr_value:
                            error_message = str(attr_value)
                            break

            return {
                'exit_code': exit_code,
                'output': output_text,
                'error_output': error_message,
                'lifecycle_state': execution.lifecycle_state
            }

        # pylint: disable=broad-except
        except Exception as e:
            logger.error("Error getting command output for %s: %s", command_id, e)
            return None

    def deploy_falcon_to_instances(self, instances: List[Dict], bucket_name: str,
                                 linux_script: str = "install.sh",
                                 windows_script: str = "install.cmd") -> Dict:
        """Deploy Falcon sensor with OS-specific scripts"""

        # Verify bucket access for both scripts
        logger.info("Verifying access to Object Storage bucket %s...", bucket_name)
        script_access = self.verify_bucket_access(bucket_name, linux_script, windows_script)

        # Filter instances based on available PAR URLs
        deployable_instances = []
        skipped_instances = []

        for instance in instances:
            os_type = instance['os_type']
            if script_access.get(os_type, False):
                deployable_instances.append(instance)
            else:
                skipped_instances.append(instance)
                logger.warning("Skipping %s (%s) - script not available", instance['display_name'], os_type)

        if not deployable_instances:
            logger.error("No instances can be deployed - missing required scripts")
            return {'successful': [], 'failed': instances, 'total': len(instances), 'skipped': skipped_instances}

        results = {
            'successful': [],
            'failed': [],
            'skipped': skipped_instances,
            'total': len(instances),
            'command_ids': {}  # Track command IDs for status checking
        }

        logger.info("Starting deployment to %d instances...", len(deployable_instances))
        logger.info("Rate limit: %d RPS, Batch size: %d", self.max_rps, self.batch_size)
        logger.info("Scripts: Linux=%s, Windows=%s", linux_script, windows_script)

        # Process instances in batches
        for i in range(0, len(deployable_instances), self.batch_size):
            batch = deployable_instances[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (len(deployable_instances) + self.batch_size - 1) // self.batch_size

            logger.info("Processing batch %d/%d (%d instances)", batch_num, total_batches, len(batch))

            # Process batch with threading but rate limiting
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(batch))) as executor:
                future_to_instance = {}

                for instance in batch:
                    # Choose PAR URL based on OS
                    script_name = linux_script if instance['os_type'] == 'linux' else windows_script

                    future = executor.submit(
                        self.create_run_command_from_storage,
                        instance['id'],
                        bucket_name,
                        script_name,
                        instance['compartment_id'],
                        instance['display_name'],
                        instance['os_type']
                    )
                    future_to_instance[future] = instance

                for future in as_completed(future_to_instance):
                    instance = future_to_instance[future]
                    try:
                        command_id = future.result()
                        if command_id:
                            results['successful'].append(instance)
                            results['command_ids'][instance['id']] = command_id
                        else:
                            results['failed'].append(instance)

                    # pylint: disable=broad-except
                    except Exception as e:
                        logger.error("Exception for instance %s: %s", instance['id'], e)
                        results['failed'].append(instance)

            # Pause between batches
            if i + self.batch_size < len(deployable_instances):
                pause_time = len(batch) * self.request_interval
                logger.info("Pausing %.2fs before next batch...", pause_time)
                time.sleep(pause_time)

        return results

    def monitor_deployment_status(self, results: Dict, check_interval: int = 30,
                                max_wait_time: int = 1800) -> Dict:
        """Monitor the status of deployment commands"""
        if not results['command_ids']:
            logger.info("No commands to monitor")
            return results

        logger.info("Monitoring %d deployment commands...", len(results['command_ids']))
        logger.info("Check interval: %ds, Max wait time: %ds", check_interval, max_wait_time)

        start_time = time.time()
        completed_commands = set()
        status_summary = {'SUCCEEDED': 0, 'FAILED': 0, 'IN_PROGRESS': 0, 'CANCELED': 0}

        while len(completed_commands) < len(results['command_ids']) and (time.time() - start_time) < max_wait_time:
            current_status = {'SUCCEEDED': 0, 'FAILED': 0, 'IN_PROGRESS': 0, 'CANCELED': 0}

            for instance_id, command_id in results['command_ids'].items():
                if command_id in completed_commands:
                    continue

                status = self.check_command_status(command_id, instance_id)
                if status:
                    state = status['lifecycle_state']
                    current_status[state] = current_status.get(state, 0) + 1

                    if state in ['SUCCEEDED', 'FAILED', 'CANCELED']:
                        if command_id not in completed_commands:
                            completed_commands.add(command_id)
                            status_summary[state] = status_summary.get(state, 0) + 1

                            if state == 'SUCCEEDED':
                                logger.info("✅ Command completed successfully for instance %s", instance_id)

                            else:
                                logger.warning("❌ Command %s for instance %s", state.lower(), instance_id)

                                # Get output for failed commands
                                if state == 'FAILED':
                                    output = self.get_command_output(command_id, instance_id)
                                    if output:
                                        exit_code = output.get('exit_code')
                                        if exit_code is not None:
                                            logger.error("   Exit code: %d", exit_code)
                                        else:
                                            logger.error("   Exit code: Not available")

                                        error_output = output.get('error_output')
                                        if error_output:
                                            logger.error("   Error: %s", error_output[:500])
                                        else:
                                            logger.error("   No error output available")
                    else:
                        status_summary['IN_PROGRESS'] = status_summary.get('IN_PROGRESS', 0) + 1

            if len(completed_commands) < len(results['command_ids']):
                in_progress = len(results['command_ids']) - len(completed_commands)
                logger.info("Status: %d succeeded, %d failed, %d in progress, %d canceled",
                            status_summary['SUCCEEDED'], status_summary['FAILED'], in_progress, status_summary.get('CANCELED', 0))
                time.sleep(check_interval)

        # Handle timeout
        if (time.time() - start_time) >= max_wait_time:
            remaining = len(results['command_ids']) - len(completed_commands)
            logger.warning("Monitoring timeout reached. %d commands still in progress.", remaining)

        # Final status report
        results['deployment_status'] = status_summary
        return results

def main():
    """Main function to handle command line arguments and orchestrate deployment."""

    parser = argparse.ArgumentParser(description='Deploy CrowdStrike Falcon to OCI instances with OS auto-discovery')
    parser.add_argument('--bucket-name', required=True, help='OCI Object Storage bucket name')
    parser.add_argument('--linux-script', default='install.sh', help='Linux installation script name (default: %(default)s)')
    parser.add_argument('--windows-script', default='install.cmd', help='Windows installation script name (default: %(default)s)')
    parser.add_argument('--compartments', nargs='+', help='Specific compartment IDs (optional)')
    parser.add_argument('--instance-name', type=str, help='Install on a specific instance by name (optional)')
    parser.add_argument('--config-file', default='~/.oci/config', help='OCI config file path (default: %(default)s)')
    parser.add_argument('--profile', default='DEFAULT', help='OCI config profile (default: %(default)s)')
    parser.add_argument('--log', action='store_true', help='Log deployment status after execution')
    parser.add_argument('--log-interval', type=int, default=30, help='Status check log in seconds (default: %(default)s)')
    parser.add_argument('--log-max-wait', type=int, default=1800, help='Maximum wait time for monitoring in seconds (default: %(default)s)')
    parser.add_argument('--batch', action='store_true', help='Run the script in non-interactive mode')

    args = parser.parse_args()

    try:
        # Initialize manager
        logger.info("Initializing OCI clients...")
        manager = FalconRunCommandManager(args.config_file, args.profile)

        # Get all instances with OS detection
        instances = manager.get_all_instances_with_os(args.compartments, args.instance_name)

        if not instances:
            logger.warning("No running instances found!")
            return

        # Show instance breakdown
        linux_instances = [i for i in instances if i['os_type'] == 'linux']
        windows_instances = [i for i in instances if i['os_type'] == 'windows']

        logger.info("Found %d instances:", len(instances))
        logger.info("  Linux: %d", len(linux_instances))
        logger.info("  Windows: %d", len(windows_instances))

        # Show sample instances
        for instance in instances[:5]:
            logger.info("  - %s (%s) - %s", instance['display_name'], instance['os_type'], instance['id'])
        if len(instances) > 5:
            logger.info("  ... and %d more", len(instances) - 5)

        # Confirm deployment
        if not args.batch:
            response = input(f"\nProceed with deployment to {len(instances)} instances? (y/N): ")
            if response.lower() not in ['y', 'yes']:
                logger.info("Deployment cancelled by user")
                return

        # Deploy with OS-specific scripts
        logger.info("\n%s", "="*50)
        logger.info("STARTING DEPLOYMENT")
        logger.info("%s", "="*50)

        results = manager.deploy_falcon_to_instances(
            instances,
            args.bucket_name,
            args.linux_script,
            args.windows_script
        )

        # Monitor deployment if requested
        if args.log:
            logger.info("\n%s", "="*50)
            logger.info("LOGGING DEPLOYMENT")
            logger.info("%s", "="*50)

            results = manager.monitor_deployment_status(
                results,
                args.log_interval,
                args.log_max_wait
            )

        # Print summary
        logger.info("\n%s", "="*50)
        logger.info("DEPLOYMENT SUMMARY")
        logger.info("%s", "="*50)
        logger.info("Total instances: %d", results['total'])
        logger.info("Commands created successfully: %d", len(results['successful']))
        logger.info("Command creation failed: %d", len(results['failed']))
        logger.info("Instances skipped (missing scripts): %d", len(results.get('skipped', [])))

        if 'deployment_status' in results:
            logger.info("\nExecution Status:")
            for status, count in results['deployment_status'].items():
                if count > 0:
                    logger.info("  %s: %d", status, count)

        if results['failed']:
            logger.info("\nFailed instances:")
            for instance in results['failed'][:10]:
                logger.info("  - %s (%s) - %s", instance['display_name'], instance['os_type'], instance['id'])
            if len(results['failed']) > 10:
                logger.info("  ... and %d more", len(results['failed']) - 10)

        if results.get('skipped'):
            logger.info("\nSkipped instances (missing scripts):")
            for instance in results['skipped'][:10]:
                logger.info("  - %s (%s) - %s", instance['display_name'], instance['os_type'], instance['id'])
            if len(results['skipped']) > 10:
                logger.info("  ... and %d more", len(results['skipped']) - 10)

        # Success rate
        deployable_count = results['total'] - len(results.get('skipped', []))
        if deployable_count > 0:
            success_rate = (len(results['successful']) / deployable_count) * 100
            logger.info("\nOverall success rate: %.1f%% (%d/%d deployable instances)",
                       success_rate, len(results['successful']), deployable_count)

    except KeyboardInterrupt:
        logger.info("\nDeployment interrupted by user")
    except Exception as e:
        logger.error("Script execution failed: %s", e)
        raise

if __name__ == "__main__":
    main()
