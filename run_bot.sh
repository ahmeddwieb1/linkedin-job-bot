#!/bin/bash

cd /home/dwieb/linkedin-job-bot

/home/dwieb/linkedin-job-bot/.venv/bin/python job_search.py >> /home/dwieb/linkedin-job-bot/cron.log 2>&1