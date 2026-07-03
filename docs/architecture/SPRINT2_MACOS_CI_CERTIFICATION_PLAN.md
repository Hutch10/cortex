# Sprint 2 macOS CI Certification Plan

## Current Status
**Sprint 2 / 2.6 is CONDITIONAL PASS.**

## Reason
The final certification step requires compiling and building the native Swift/Objective-C iOS bridge. This necessitates the macOS/Xcode environment, which is currently unavailable locally on this Windows workstation.

## Recommended Solution
Leverage a GitHub Actions macOS runner (`macos-latest`) to execute the certification step remotely without requiring a physical Mac.

## Required Prerequisite
Since no GitHub remote is currently configured for this repository, the immediate next action is for the user to create a private GitHub repository, configure the local git remotes, and push the source code to GitHub.

## Exact Command to Certify
Once the CI pipeline checks out the repository, the following commands must run to successfully certify the iOS shell:

```bash
cd apps/vitalicast-ios-shell/ios/App
xcodebuild -workspace App.xcworkspace -scheme App -sdk iphonesimulator clean build
```

## Proposed CI Workflow
The following workflow YAML should be added to `.github/workflows/vitalicast-ios-certification.yml` *after* the GitHub remote is configured. This workflow runs on manual dispatch and executes the build against the iOS shell code.

```yaml
name: Vitalicast iOS Certification

on:
  workflow_dispatch:

jobs:
  certify-ios:
    runs-on: macos-latest
    
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4
        with:
          submodules: recursive
          
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install Frontend Dependencies
        working-directory: ./frontend
        run: npm ci
        
      - name: Install iOS App Dependencies & Sync
        working-directory: ./apps/vitalicast-ios-shell
        run: |
          npm ci
          npx cap sync ios
          
      - name: Run Xcodebuild Certification
        working-directory: ./apps/vitalicast-ios-shell/ios/App
        run: |
          xcodebuild -workspace App.xcworkspace -scheme App -sdk iphonesimulator clean build
```
