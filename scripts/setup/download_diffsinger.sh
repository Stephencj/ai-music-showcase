#!/usr/bin/env bash
# Download the DiffSinger English voicebank for the "studio" vocal engine.
# The voicebank (~555 MB) is NOT committed (data/models/ is gitignored) and
# is CC BY-NC-ND (personal/non-commercial use). Re-run on a fresh clone.
set -euo pipefail

DEST="data/models/diffsinger"
VB_URL="https://github.com/spicytigermeat/tiger_diffsinger/releases/download/v106/TIGER_DS_v106_PACK.zip"

mkdir -p "$DEST"
cd "$DEST"

if [ -f tiger_vb/dsacoustic/acoustic.onnx ]; then
  echo "Voicebank already present at $DEST/tiger_vb — nothing to do."
  exit 0
fi

echo "Downloading Tiger DiffSinger voicebank (~555 MB)…"
curl -fL -o tiger.zip "$VB_URL"
echo "Unzipping…"
unzip -q -o tiger.zip -d tiger
unzip -q -o "tiger/TIGER_DS_v106_PACK/Voice Library/TIGER_DS_v106.zip" -d tiger_vb
rm -rf tiger tiger.zip
echo "Done. Voicebank at $DEST/tiger_vb"
echo "Note: studio vocals also need 'pip install onnxruntime g2p-en' (in requirements.txt)."
