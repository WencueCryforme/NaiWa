# Contributing Guide

[简体中文](./CONTRIBUTING.md) |
[English]


## Basic Flow

fork this repository -> clone your fork to local -> make changes locally -> commit and push to your remote fork -> create a PR -> wait for review

> Do not modify `.gitignore` without permission, and do not commit your local working leftovers to the repository


## Adding Sticker Packs

- All sticker packs are organized by album; follow the directory convention and create a new album folder under `dist/meme/`
- Store **compressed versions** of `.jpg` (500KB or less preferred) or `.gif` (2MB or less preferred) files in your album folder, and name the files to briefly describe the sticker content or meaning
- Submit a PR to this repository, and attach your album's **uncompressed versions** as one `.zip` archive (named after the album) in the PR comments, then wait for review
- Once approved, both the uncompressed and compressed versions of your sticker album will be uploaded to the Assets list of a version Release, and the album will be listed in the [sticker pack archive list document](docs/meme-list.md)
- Alternatively, you can submit the `.zip` archive of your **uncompressed versions** by following the flow in the [#Adding High-Definition Versions](#adding-high-definition-versions) section, though this will take longer to review and categorize

> To compress sticker packs, it is recommended to use the `scripts/img_resize.py` or `scripts/gif_resize.py` scripts provided in this repository


## Adding High-Definition Versions

When you have the **high-definition versions** of some sticker packs already in the repository, and your versions are higher in definition than the **raw** level sticker files already in a repository Release, you can contribute them through the following standardized flow:
- Pack your sticker packs into a `.zip` archive with the following hierarchy
```
raw
└─ album name
   └─ sticker file
```
- Rename the archive in the standardized form `update.raw.meme.<album name>-yyyy-MM-dd.zip`, where `yyyy-MM-dd` should be replaced with the **UTC date** at packing time
- [Create a new Issue] and attach your sticker `.zip` archive


## Removing Sticker Packs

If some sticker packs already in the repository are, in your opinion or in fact, **plagiarized, infringing, illegal** or otherwise problematic, you can request their removal:
- [Create a new Issue] to request the removal, and attach your reasons and the repository paths of those sticker packs
- If the Issue comments uphold your reasons, or the non-compliance of those sticker packs is obvious, the repository will remove them as soon as possible
- The scope of removal is limited to **deleting the archive attached to the corresponding Release and adding a repository commit that removes the corresponding sticker packs**, but users can still recover their compressed versions by tracing back the repository git history
- For the negative impact those sticker packs have already caused in reality, on the internet, or on social media, **the provider of the sticker files is responsible**, and the author of this repository and the community **bear no** joint liability
