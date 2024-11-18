#!/bin/bash

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install requirements
pip3 install -r requirements.txt

# Run the main.py script
python3 main.py

# Deactivate the virtual environment
deactivate
