import os
import json
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import fastf1
import pandas as pd
from fastf1.ergast import Ergast

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
ARCHIVE_FILE = "f1_race_archive.json"

def check_process_race():
    today = datetime.now().date()
    seven_days_ago = today - timedelta(days=7)
    current_year = today.year
    if not os.path.exists('fastf1_cache'):
        os.makedirs('fastf1_cache')


    fastf1.Cache.enable_cache('fastf1_cache')

    schedule['Session5Date'] = pd.to_datetime(schedule['Session5Date'])

    schedule = fastf1.get_event_schedule(current_year)
    recent_races = schedule[(schedule['EventFormat'] != 'testing') & 
                            (schedule['Session5Date'].dt.date >= seven_days_ago)&
                            (schedule['Session5Date'].dt.date <= today)]


    if recent_races.empty:
        return

    target_event = recent_races.iloc[0]
    race_round = target_event['RoundNumber']
    race_name = target_event['EventName']
    race_date = target_event['Session5Date'].strftime('%Y-%m-%d')

    session = fastf1.get_session(current_year, race_round, 'R')
    session.load(laps=True, telemetry=False, weather=False)

    results = session.results
    top_10 = results.iloc[:10]
    positions_list = [{"position": int(row['Position']), "driver": row['Abbreviation'], "team": row['TeamName'], "status": row['Status']} for idx, row in top_10.iterrows()]

    fastest_lap = session.laps.pick_fastest()
    fastest_driver = fastest_lap['Driver']
    fastest_time = str(fastest_lap['LapTime']).split()[-1]

    winner_laps = session.laps.pick_driver(top_10.iloc[0]['Abbreviation'])
    compounds_used = list(winner_laps['Compound'].dropna().unique())

    ergast = Ergast()
    driver_standings_df = ergast.get_driver_standings(season=current_year, round=race_round).content[0]
    constructor_standings_df = ergast.get_constructor_standings(season=current_year, round=race_round).content[0]


    top_drivers = driver_standings_df.head(10)[['position', 'points', 'wins', 'givenName', 'familyName']].copy()
    top_drivers['driver_name'] = top_drivers['givenName'] + " " + top_drivers['familyName']
    drivers_list = top_drivers.to_dict(orient='records')

    top_constructors = constructor_standings_df.head(5)[['position', 'points', 'wins', 'constructorName']].copy()
    top_constructors['team_name'] = top_constructors['constructorName']
    constructors_list = top_constructors.to_dict(orient='records')

    race_payload = {
        "metadata": {
            "project_source": "f1_mvp_pipeline",
            "extracted_at": datetime.now().isoformat(),
            "season": int(current_year),
            "round": int(race_round),
            "track_name": race_name,
            "race_date": race_date,
            "data_version": "1.1"
        },
        "race_summary": {
            "season": int(current_year),
            "round": int(race_round),
            "track_name": race_name,
            "winner": top_10.iloc[0]['Abbreviation'],
            "fastest_lap": {"driver": fastest_driver, "time": fastest_time},
            "winner_compounds_used": compounds_used,
            "top_10_classification": positions_list
        },
        "championship_standings":{
            "drivers": drivers_list,
            "constructors": constructors_list
        }
    }

    save_to_archive(race_payload)
    send_email_summary(race_name, race_payload)

def save_to_archive(payload):
    archive_data = []
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, 'r') as f:
            try:
                archive_data = json.load(f)
            except json.JSONDecodeError:
                pass
    archive_data.append(payload)
    with open(ARCHIVE_FILE, 'w') as f:
        json.dump(archive_data, f, indent=4)
    
def send_email_summary(race_name, payload):
    summary = payload['race_summary']
    standings = payload['championship_standings']
    body = f"Race Summary: {race_name}\n{'='*30}\n\nWinner: {summary['winner']}\nFastest Lap: {summary['fastest_lap']['driver']} ({summary['fastest_lap']['time']})\nWinner Tire Strategy: {', '.join(summary['winner_compounds_used'])}\n\nTop 10 Classification:\n"
    for pos in summary['top_10_classification']:
        body += f"{pos['position']}. {pos['driver']} - {pos['team']} ({pos['status']})\n"

    body += f"\n Driver Championship Standings\n{'-'*30}\n"
    for d in standings['drivers']:
        body += f"{d['position']}. {d['driver_name']} - {d['points']} pts (Wins: {d['wins']})\n"

    body += f"\n Constructor Championship Standings\n{'-'*30}\n"
    for c in standings['constructors']:
        body += f"{c['position']}. {c['team_name']} - {c['points']} pts (Wins: {c['wins']})\n"

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = f"F1 Weekend Review: {race_name}"
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_RECIPIENT, msg.as_string())
        server.quit()
        print("Notification sent successfully!")
    except Exception as e:
        print(f"Failed to send email:{e}")

if __name__ == "__main__":
    check_process_race()