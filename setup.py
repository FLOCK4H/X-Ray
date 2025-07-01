# setup.py 

from setuptools import setup, find_packages

setup(
    name="x-ray",
    version="0.1.25",
    package_dir={"": "src"},      # <─ tell setuptools where packages live
    packages=find_packages("src"),# <─ finds x_ray and x_ray.launchlab
    include_package_data=True,
    install_requires=[
        "construct",
        "solana",
        "solders",
        "requests",
        "asyncio",
        "aiohttp",
        "httpx",
        "base58",
        "dotenv"
    ],
    author="FLOCK4H",
    description="X-Ray",
    entry_points={
        "console_scripts": [
            "x-ray=x_ray.main:run",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)