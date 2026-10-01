#!/bin/bash
# wrapper script بيشغّل البوت من جوه cron، ومسجّل أي output/error في ملف log
# بدل ما يختفي في العدم (مشكلة شائعة جداً مع cron jobs).

# يدخل فولدر المشروع الأول — عشان أي مسار نسبي جوه الكود
# (زي seen_jobs.json) يتكتب في المكان الصح، مش في / أو /home/dwieb
cd /home/dwieb/linkedin-job-bot

# بيشغّل بايثون بتاع الـ virtual environment بتاع المشروع (.venv) —
# مش بايثون النظام — عشان يلاقي المكتبات اللي اتعملها pip install فيها
# (requests, beautifulsoup4, python-dotenv...).
# ">> cron.log 2>&1" بتحوّل الـ output العادي (stdout) والأخطاء (stderr)
# مع بعض وتضيفهم في آخر ملف cron.log، بدل ما يضيعوا أو يوصلولك كإيميلات.
/home/dwieb/linkedin-job-bot/.venv/bin/python job_search.py >> /home/dwieb/linkedin-job-bot/cron.log 2>&1