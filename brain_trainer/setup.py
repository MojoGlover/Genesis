from setuptools import setup, find_packages
setup(
    name="brain_trainer",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "torch>=2.0.0",
        "transformers>=4.40.0",
        "trl>=0.8.0",
        "peft>=0.10.0",
        "datasets>=2.18.0",
        "accelerate>=0.28.0",
        "bitsandbytes>=0.43.0",
        "pyyaml>=6.0",
        "scipy",
    ],
    python_requires=">=3.10",
)
