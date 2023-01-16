import functools
import os
import re
import requests
import csv
import sys
from datetime import time, timedelta

import argparse


#print(response.json())

class event_type:
    GOAL = 0
    PENALTY = 1
    ASSIST = 2

class game_event:
    def toPeriod(self, int_period):
        int_period = int(int_period)
        if int_period == 1:
            return str(int_period) + 'st'
        elif int_period == 2:
            return str(int_period) + 'nd'
        elif int_period == 3:
            return str(int_period) + 'rd'
        else:
            return str(int_period) + 'th'
    def __init__(self, id, name, start_time, end_time, period, participant, partNumber, event_type, penalty_duration = 0, event_subtype = ''):
        self.id = id
        self.name = name
        self.participant = participant
        self.partNumber = partNumber
        self.start_time = start_time
        self.end_time = end_time
        self.period = self.toPeriod(period)
        self.event_type = event_type
        self.event_subtype = event_subtype
        self.penalty_duration = penalty_duration

def score_sort(item1, item2):
    if(item1.period < item2.period or (item1.period == item2.period and item1.start_time >= item2.start_time)):
        return -1
    else:
        return 1

class score_track:
    def __init__(self):
        self.scores_ = []
    def add_score(self, score):
        self.scores_.append(score)
        self.scores_ = sorted(self.scores_, key=functools.cmp_to_key(score_sort))
    def score_str(self, period, time, team1, team2):
        dict = {team1: 0, team2: 0}
        for score in filter(lambda x: x.event_type == event_type.GOAL, self.scores_):
            if score.period > period or (score.period == period and score.start_time < time):
                continue
            dict[score.name] += 1
        vals = list(dict.values())
        return '' + str(vals[0]) + ' -- ' +  str(vals[1]) 

def collectGameTime(dateObj): 
    return timedelta(minutes=int(dateObj['minutes']), seconds=int(dateObj['seconds']))

def computePenalty(start, dur):
    if start.seconds <= dur.seconds:
        return timedelta(minutes=0, seconds=0)
    return start - dur
    
def obtainGoalCode(dict):
    if dict['isPowerplay']:
        return 'PPG'
    elif dict['isShorthanded']:
        return 'SHG'
    elif dict['isEmptyNet']:
        return 'ENG'
    elif dict['isPenaltyShot']:
        return 'PSG'
    else:
        return 'REG'


def writeGameToFile(hockey_csv, response, date):
    rj = response.json()
    idTeamName = {}
    out_writer = csv.writer(hockey_csv)
    for team in rj['teams']:
        idTeamName[team['id']] = team['name']
    teamNames = list(idTeamName.values())
    scores = score_track()
    for goal in rj['goals']:
        scores.add_score(game_event(goal['teamId'], idTeamName[goal['teamId']], collectGameTime(goal['gameTime']), collectGameTime(goal['gameTime']), goal['gameTime']['period'], goal['participant']['fullName'], goal['participant']['number'], event_type.GOAL, 0, obtainGoalCode(goal)))
        for assist in goal['assists']:
            scores.add_score(game_event(goal['teamId'], idTeamName[goal['teamId']], collectGameTime(goal['gameTime']), collectGameTime(goal['gameTime']), goal['gameTime']['period'], assist['fullName'], assist['number'], event_type.ASSIST, 0, obtainGoalCode(goal)))

    for pen in rj['penalties']:
        pen_period = int(pen['gameTime']['period'])
        pen_starttime = collectGameTime(pen['gameTime'])
        pen_endtime = pen_starttime
        pen_duration = 0
        if 'description' in pen['duration']:
            pen_duration = int(re.findall("\d+", pen['duration']['description'])[0])
            pen_endtime = computePenalty(collectGameTime(pen['gameTime']), timedelta(minutes=pen_duration))
        scores.add_score(game_event(pen['teamId'], idTeamName[pen['teamId']], pen_starttime, pen_endtime , pen_period, pen['participant']['fullName'], pen['participant']['number'], event_type.PENALTY, pen_duration, pen['infraction']))
        
        if pen_starttime.total_seconds() < pen_duration * 60 and pen_period < 3:
            carryover_start = timedelta(minutes=20, seconds=0)
            carryover_duration = timedelta(minutes=pen_duration) - pen_starttime
            carryover_endtime = carryover_start - carryover_duration
            scores.add_score(game_event(pen['teamId'], idTeamName[pen['teamId']], carryover_start, carryover_endtime, pen_period + 1, pen['participant']['fullName'], pen['participant']['number'], event_type.PENALTY, pen_duration, pen['infraction']))
    
    for score in scores.scores_:
        if score.event_type == event_type.GOAL:
            out_writer.writerow([teamNames[0], teamNames[1], date, 'GOAL', score.event_subtype, score.participant, score.partNumber, score.name, score.start_time, score.end_time, score.period, 0, scores.score_str(score.period, score.start_time, teamNames[0], teamNames[1])])
    
        if score.event_type == event_type.ASSIST:
            out_writer.writerow([teamNames[0], teamNames[1], date, 'ASSIST', score.event_subtype, score.participant, score.partNumber, score.name, score.start_time, score.end_time, score.period, 0, scores.score_str(score.period, score.start_time, teamNames[0], teamNames[1])])

        if score.event_type == event_type.PENALTY:
            out_writer.writerow([teamNames[0], teamNames[1], date, 'PENALTY', score.event_subtype, score.participant, score.partNumber, score.name, score.start_time, score.end_time, score.period, score.penalty_duration, scores.score_str(score.period, score.start_time, teamNames[0], teamNames[1])])

def main():
    parser = argparse.ArgumentParser('Collect data from VIAHA webpage and dump to csv spreadsheets.')
    parser.add_argument('-s','--separate', dest='separate', action='store_const', const=True, default=False, help='If enabled, games will be split into separate files.')
    parser.add_argument('scheduleId', type=int, nargs='?', help='Provide the ID of the schedule for the games you want to collect.')
    parser.add_argument('teamId', type=int, nargs='?', help='Provide the team you are interested in from the provided schedule')

    args=parser.parse_args()

    if args.scheduleId is None or args.teamId is None:
        raise Exception('Cannot run script without a schedule and team ID')

    gameId = sys.argv[1]
    scheduleUrl = 'https://api.hisports.app/api/games'
    paramStr = '?filter={{"where":{{"and":[{{"scheduleId":{}}},{{"or":[{{"homeTeamId":{}}},{{"awayTeamId":{}}}]}}]}},"include":["arena","schedule","group","teamStats"],"order":["startTime ASC","id DESC"],"limit":null,"skip":null}}'.format(args.scheduleId, args.teamId, args.teamId)
    headers = {'authorization' : 'API-Key f75fa549e81421f19dc929bc91f88820b6d09421'}
    sess = requests.Session()
    req = requests.Request('GET', scheduleUrl, headers=headers)
    prep = req.prepare()
    prep.url += paramStr
    resp = sess.send(prep)

    collectfilename = 'games-season-{}-{}-{}.csv'.format(resp.json()[0]['seasonId'], args.scheduleId, args.teamId)
    if args.separate == False:
        if os.path.isfile(collectfilename):
            os.remove(collectfilename)
        with open(collectfilename, 'a') as file:
            out_writer = csv.writer(file)
            out_writer.writerow(['Home Team', 'Away Team', 'Date', 'Event', 'Event Type', 'Player Name', 'Player Number', 'Player Team', 'Start Time', 'End Time', 'Period', 'Penalty Mins', 'Score'])


    for game in resp.json():
        gameUrl = 'https://api.hisports.app/api/games/{}/boxScore'.format(game['id'])
        req = requests.Request('GET', gameUrl, headers=headers)
        resp = sess.send(req.prepare())
        if args.separate:
            with open('game-{}-{}-{}.csv'.format(game['date'], args.scheduleId, args.teamId), 'w+') as file:
                out_writer = csv.writer(file)
                out_writer.writerow(['Home Team', 'Away Team', 'Date', 'Event', 'Event Type', 'Player Name', 'Player Number', 'Player Team', 'Start Time', 'End Time', 'Period', 'Penalty Mins', 'Score'])
                writeGameToFile(file, resp, game['date'])
        else:
            with open(collectfilename, 'a') as file:
                writeGameToFile(file, resp, game['date'])
        
        


if __name__ == '__main__':
    main()