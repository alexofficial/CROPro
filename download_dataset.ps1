$URL = 'https://www.dropbox.com/scl/fo/nu8jikkzzue5ftojk54oo/h?rlkey=j91kg32huzcl0c7k3rahwrji9&dl=0'
# $ZIP_FILE = '.\dataset\dataset.zip'
# $DIRECTORY = '.\dataset'

$ZIP_FILE = '.\dataset\dataset.zip'
$DIRECTORY = '.\dataset'

# Ensure the directory exists
if (-not (Test-Path $DIRECTORY)) {
    New-Item -ItemType Directory -Force -Path $DIRECTORY
}

# Download the ZIP file
Write-Output "Downloading file..."
Invoke-WebRequest -Uri $URL -OutFile $ZIP_FILE

# Verify the file exists and has a non-zero size
if ((Test-Path $ZIP_FILE) -and ((Get-Item $ZIP_FILE).length -gt 0)) {
    Write-Output "File downloaded successfully. Size: $((Get-Item $ZIP_FILE).length) bytes."
    
    # Attempt to open the ZIP file to verify its integrity
    try {
        $zip = [System.IO.Compression.ZipFile]::OpenRead($ZIP_FILE)
        $zip.Dispose()
        
        # Unzip the file
        Expand-Archive -LiteralPath $ZIP_FILE -DestinationPath $DIRECTORY -Force
        Write-Output "File unzipped successfully."
    }
    catch {
        Write-Error "The downloaded file is either not a valid ZIP file or it is corrupt."
    }
}
else {
    Write-Error "Failed to download the file or the file is empty."
}

# # Clean up the ZIP file
# Remove-Item $ZIP_FILE -ErrorAction SilentlyContinue