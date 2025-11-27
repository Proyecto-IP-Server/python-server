#!/bin/bash
sudo nginx -c `pwd`/nginx.conf

source venv/bin/activate

fastapi dev main.py &

cd ../Proyecto-IP

npm start &
