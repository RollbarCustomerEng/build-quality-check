# build-quality-check
Project to check the quality of a build using the Rollbar Versions API

# build_quality_check.py
Script to query the the Versions API to check the number of New or Reactivated error Items for a particular code_verion in a specific environment

##Arguments:

--access-token - A Rollbar access token with read scope
--code-version - The code_version of the error in Rollbar
--item-threshold - The number of items above which quality is considered Failed

--checks - The number of times you check the item counts. Used for progressive deployments (canary, blue/green)
--check-seconds - The number of seconds between each check. Used for progressive deployments

##Return Codes:

0 - Success - No new items
1 - New Items - New items of level Error or Critical
2 - Reactivated Items - Reactivated items of level Error or Critical
3 - New and Reactivated Items - New and Reactivated items of level Error or Critical
100 - General Error
101 - Web Request Error

# run_task.sh
Shell script that reads the access token from an environment variable and call the script build_quality_check.py for a specific code_version and environment
This script just checks 1 time for errors