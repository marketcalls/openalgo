from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/api/cron', methods=['GET'])
def cron_job():
    # This is where you would put the logic you want to run on a schedule
    print('Cron job ran successfully')
    return jsonify(message='Cron job ran successfully'), 200
