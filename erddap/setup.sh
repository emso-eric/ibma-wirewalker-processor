#!/bin/bash

echo "Stopping container"
docker compose stop

mkdir -p erddap/erddapData
mkdir -p datasets

echo "Copying default configuration"
cp conf/datasets_default.xml conf/datasets.xml

echo "Starting container"
docker compose up -d