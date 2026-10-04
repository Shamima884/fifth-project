"""RxSpark — Digital Prescription System for Doctors.

Entry point: python run.py
"""
from rxspark import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=app.config["DEBUG"])
