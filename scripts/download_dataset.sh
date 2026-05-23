#!/bin/sh
set -e

# Download PI-CAI public images from Zenodo and annotations from DIAGNijmegen/picai_labels.
# By default this downloads fold 0 only (~5.4 GB). Set CROPRO_PICAI_FOLDS="0 1 2 3 4"
# to download all public folds (~26.9 GB).

DATASET_ROOT="${CROPRO_DATASET_ROOT:-dataset/PI-CAI}"
IMAGES_DIR="$DATASET_ROOT/images"
ARCHIVES_DIR="$DATASET_ROOT/archives"
LABELS_DIR="$DATASET_ROOT/picai_labels"
FOLDS="${CROPRO_PICAI_FOLDS:-0}"

mkdir -p "$IMAGES_DIR" "$ARCHIVES_DIR"

for fold in $FOLDS; do
    archive="$ARCHIVES_DIR/picai_public_images_fold${fold}.zip"
    url="https://zenodo.org/api/records/6624726/files/picai_public_images_fold${fold}.zip/content"

    echo "Downloading PI-CAI public images fold ${fold}..."
    curl -L -C - "$url" --output "$archive"

    echo "Unpacking fold ${fold} into $IMAGES_DIR..."
    unzip -n "$archive" -d "$IMAGES_DIR"
done

if [ ! -d "$LABELS_DIR/.git" ]; then
    echo "Cloning PI-CAI labels into $LABELS_DIR..."
    git clone https://github.com/DIAGNijmegen/picai_labels "$LABELS_DIR"
else
    echo "Updating PI-CAI labels in $LABELS_DIR..."
    git -C "$LABELS_DIR" pull --ff-only
fi

echo "PI-CAI data is ready under $DATASET_ROOT"
