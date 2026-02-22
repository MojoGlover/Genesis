from setuptools import setup, find_packages

setup(
    name="wix_connector",
    version="1.0.0",
    description="Wix Headless API connector — read/write CMS, blog, store, contacts",
    packages=find_packages(),
    install_requires=["httpx>=0.27.0"],
)
