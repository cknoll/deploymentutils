# deploymentutils

This repo contains a small python package to facilitate deployment of some personal projects.


## Overview

This package provides a thin layer on top of [fabric](https://www.fabfile.org/) to execute commands with a state like
- current working directory
- activated virtual environment (not yet implemented)

It also tries to simplify to deploy/maintain multiple instances of the same software but with varying fixtures, including a local instances for testing.

## Motivation

The package is mainly intended to facilitate deployment tasks (eg. for django apps) by running a simple python script.
Compared to configuration management tools like *Ansible* this approach is far less powerful and scalable.
However, it might be easier to understand for developers and thus lowering the hurdle to deploy applications by them selves.


## Status

Still under development and poorly tested.
