from setuptools import setup, find_packages

try:
    from pypandoc import convert
    def read_markdown(file: str) -> str:
        return convert(file, "rst")
except ImportError:
    def read_markdown(file: str) -> str:
        return open(file, "r").read()

setup(
    name="openstack-tools",
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    install_requires=open("requirements.txt", "r").readlines(),
    url="https://github.com/wtsi-hgi/openstack-tools",
    license="GPL3",
    description="Tools for working with OpenStack",
    long_description=read_markdown("README.md"),
    entry_points={
        "console_scripts": [
            "glancecp=openstacktools.glancecp:main",
            "glancenuke=openstacktools.glancenuke:main"
        ]
    }
)
