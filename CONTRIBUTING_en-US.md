# Contributing Guide

[简体中文](./CONTRIBUTING.md) |
[English]

## Basic Flow

fork this repository -> clone your fork to local -> make changes locally -> commit and push to your remote fork -> create a PR -> wait for review

> Do not modify `.gitignore` without permission, and do not commit your local working leftovers to the repository

## Adding Sticker Packs

- All sticker packs are organized by album; follow the directory convention and create a new album folder under `dist/meme/`
- Store **compressed versions** of `.png` or `.gif` files (not larger than 500KB) in your album folder, and name the files to briefly describe the sticker content or meaning
- Submit a PR to this repository, and attach your album's **uncompressed versions** as one `.zip` archive (named after the album) in the PR comments, then wait for review
- Once approved, your sticker album will be uploaded to the Assets list of a version Release, and listed in the sticker pack archive list document (`docs/meme-raw-list.md`)

> For compression, it is recommended to use the `scripts/img_to_png.py` script in this repository