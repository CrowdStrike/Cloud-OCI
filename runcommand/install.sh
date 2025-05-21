#!/usr/bin/bash

OCID=""
VAULT_NAME=""
BUCKET_URL=""

# Check for required variables
if [ -z "$OCID" ] || [ -z "$VAULT_NAME" ] || [ -z "$BUCKET_URL" ]; then
    echo "Error: Required variables not set" >&2
    echo "Please set OCID, VAULT_NAME, and BUCKET_URL in this script before running this script" >&2
    exit 1
fi

# Get system architecture
ARCH=$(uname -m)

# Set the appropriate file suffix based on architecture
if [ "$ARCH" = "aarch64" ]; then
    ARCH_SUFFIX="arm64"
elif [ "$ARCH" = "x86_64" ]; then
    ARCH_SUFFIX="x86_64"
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi

# Fetch the list of objects in the bucket
echo "Fetching available installers..."
LISTING=$(curl -s "${BUCKET_URL}/")

if [ $? -ne 0 ]; then
    echo "Failed to get listing from bucket"
    exit 1
fi

# Parse the JSON to find matching installers for our architecture
# Using grep and sed for basic JSON parsing to avoid dependencies
PATTERN="falcon-installer-[0-9.]*-linux-${ARCH_SUFFIX}"
INSTALLERS=$(echo "$LISTING" | grep -o "\"name\":\"$PATTERN\"" | sed 's/"name":"//g' | sed 's/"//g')

if [ -z "$INSTALLERS" ]; then
    echo "No matching installers found for architecture: ${ARCH_SUFFIX}"
    exit 1
fi

# Sort versions and get the latest one
LATEST_INSTALLER=$(echo "$INSTALLERS" | sort -V | tail -n 1)

echo "Found latest installer: $LATEST_INSTALLER"
DOWNLOAD_URL="${BUCKET_URL}/${LATEST_INSTALLER}"

echo "Downloading ${LATEST_INSTALLER}..."
curl -fsSL -o "/tmp/${LATEST_INSTALLER}" "${DOWNLOAD_URL}"

if [ $? -eq 0 ]; then
    echo "Download successful: /tmp/${LATEST_INSTALLER}"
    # Make the installer executable
    chmod +x "/tmp/${LATEST_INSTALLER}"
    # You can add execution command here if needed
    sudo /tmp/"${LATEST_INSTALLER}" --verbose --enable-file-logging --user-agent=falcon-oci-run-cmd/0.1.0 --oci-compartment-id $OCID --oci-vault-name $VAULT_NAME
    exit 0
else
    echo "Failed to download installer"
    exit 1
fi
