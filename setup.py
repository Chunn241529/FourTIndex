from setuptools import setup, find_packages, find_namespace_packages

setup(
    name="fourtindex",
    version="0.1.0",
    description="Local Codebase Indexer & MCP Assistant",
    author="trung",
    py_modules=["main"],
    packages=find_namespace_packages(include=["src", "src.*"]),
    package_data={
        "src": ["config.yaml", "dashboard/index.html"],
    },
    include_package_data=True,
    install_requires=[
        "chromadb>=0.4.24",
        "ollama>=0.2.1",
        "mcp>=1.0.0",
        "pyyaml>=6.0.1",
        "rich>=13.7.1",
        "pathspec>=0.12.1",
        "python-dotenv>=1.0.1",
        "watchdog",
    ],
    extras_require={"dev": ["pytest>=8.0", "pytest-cov>=5.0"]},
    entry_points={
        "console_scripts": [
            "fourtindex=main:main",
        ],
    },
    python_requires=">=3.10",
)
