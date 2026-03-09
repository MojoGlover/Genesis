from setuptools import setup, find_packages

setup(
    name="runpod_module",
    version="1.0.0",
    description="RunPod burst GPU router for Engineer0 — offload heavy AI tasks to serverless GPUs",
    packages=find_packages(),
    install_requires=[
        "runpod>=1.6.0",
    ],
)
