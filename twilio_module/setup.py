from setuptools import setup, find_packages

setup(
    name="twilio_module",
    version="1.0.0",
    description="Twilio integration for Engineer0 — SMS alerts, voice calls, ConversationRelay AI phone bridge",
    packages=find_packages(),
    install_requires=[
        "twilio>=8.0.0",
        "flask>=2.0.0",
        "websockets>=12.0",
    ],
)
