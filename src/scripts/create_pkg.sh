#!/bin/bash

echo "Executing create_pkg.sh..."
pip install virtualenv

pwd

cd $path_cwd
cd src
dir_name=lambda_dist_pkg/
mkdir $dir_name

# Create and activate virtual environment...
virtualenv -p $runtime env_$function_name
source $path_cwd/env_$function_name/bin/activate

# Installing python dependencies...
FILE=$path_cwd/requirements.txt
cat $FILE
if [ -f "$FILE" ]; then
  echo "Installing dependencies..."
  echo "From: requirement.txt file exists..."
  pip download -r "$FILE" --platform manylinux2014_x86_64 --only-binary=:all:
#  ls -altr
  unzip "*.whl"
  rm -rf *.whl

else
  echo "Error: requirement.txt does not exist!"
fi

# Deactivate virtual environment...
deactivate

# Create deployment package...
echo "Creating deployment package..."
cp -r  env_$function_name/lib/$runtime/site-packages/* $path_cwd/
#ls -altr
# Removing virtual environment folder...
echo "Removing virtual environment folder..."
rm -rf $path_cwd/env_$function_name

echo "Finished script execution!"