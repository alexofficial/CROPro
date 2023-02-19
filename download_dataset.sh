
# CROPro dataset examples
URL=https://www.dropbox.com/sh/88g0brnkfuoyy3u/AAB2IjQezo_XJomdBsRRBijWa?dl=0
ZIP_FILE=./dataset.zip
mkdir -p ./
wget -N $URL -O $ZIP_FILE
unzip $ZIP_FILE -d ./dataset/
rm $ZIP_FILE

    