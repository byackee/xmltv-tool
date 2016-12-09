import plac
#import xml.etree.ElementTree as ET
from lxml import etree as ET
#from lxml.etree import XMLParser
from datetime import datetime
from datetime import timedelta
import calendar
from yattag import indent
import sys
import pytz
import io

stats_accumulate = dict()
channel_accumulate = dict()
channel_count = 0

def print_warning(message):
    print('WARNING: ' + str(message), file=sys.stderr)

def parse_time(time):
    return datetime.strptime(time, '%Y%m%d%H%M%S %z')

def encode_time(time):
    return datetime.strftime(time, '%Y%m%d%H%M%S %z')

def accumulate_by_date(Y,M,D, duration):
    if Y not in stats_accumulate:
        stats_accumulate[Y] = dict()
        stats_accumulate[Y][M] = dict()
    else:
        if M not in stats_accumulate[Y]:
            stats_accumulate[Y][M] = dict()

    if not duration:
        duration = timedelta(0)

    if D in stats_accumulate[Y][M]:
        stats_accumulate[Y][M][D] = stats_accumulate[Y][M][D] + duration
        #print('Adding {0} duration into {1} {2} {3}, now is {4}'.format(duration, Y, M, D, stats_accumulate[Y][M][D]))
    else:
        stats_accumulate[Y][M][D] = duration

def accumulate_channel(channel_id):
    if channel_id in channel_accumulate:
        channel_accumulate[channel_id] += 1
    else:
        channel_accumulate[channel_id] = 1

def get_program_title(program):
    title = program.find('title')
    if title is None:
        return None
    if title.text is None:
        return ''
    return title.text

def get_program_duration(program):
    stop = program.attrib['stop']
    start = program.attrib['start']
    if start and stop:
        duration = parse_time(stop) - parse_time(start)
        if duration.days < 0:
            print_warning('Program without correct start / stop fields: ' +  get_program_title(program))
            return 0
        return duration
    else:
        return 0

def do_print_days(xmltv):
    programs = xmltv.findall('./programme')

    for program in programs:
        start = parse_time(program.attrib['start'])
        accumulate_by_date(start.year, start.month, start.day, get_program_duration(program))

    for Y in stats_accumulate:
        for M in stats_accumulate[Y]:
            for D in stats_accumulate[Y][M]:
                print('{0} {1} {2} {3:02d}: {4}'.format(calendar.day_name[datetime(Y,M,D).weekday()][0:3], Y,M,D, stats_accumulate[Y][M][D]))

def do_print_channels(xmltv):
    global channel_count
    channels = xmltv.findall('./channel')
    programs = xmltv.findall('./programme')

    for program in programs:
        accumulate_channel(program.attrib['channel'])

    for channel in channels:
        accumulate_channel(channel.attrib['id'])

    for c in channel_accumulate:
        print(c + ': ' + str(channel_accumulate[c]))

def do_print_programs(xmltv, duration_instead_of_stop):
    programs = xmltv.findall('./programme')

    for program in programs:
        start = parse_time(program.attrib['start']).strftime('%a %Y-%m-%d %H:%M %z')
        stop = parse_time(program.attrib['stop']).strftime('%a %Y-%m-%d %H:%M %z')
        channel = program.attrib['channel']
        title = get_program_title(program)
        if title is None:
            print('{0}  {1}'.format(str(start), channel))
        else:
            if duration_instead_of_stop:
                print('{0}  {1}\t - {2} {3}'.format(str(start), channel, get_program_duration(program), title))
            else:
                print('{0}  {1} {2}\t - {3}'.format(str(start), stop, channel, title))
				
def xmltv_add_program(xmltv, program):
    xmltv.append(program)

xmltv_channels = dict()

def xmltv_add_channel(xmltv, channel):

    id = channel.attrib['id']

    if id not in xmltv_channels:
        xmltv_channels[id] = channel
        xmltv.append(channel)

def main(inspect: ('print stats about the files instead of the resulting file. Equivalent to -cd','flag','i'),
        debug: ('print debug statements during the execution of the program','flag','D'),
        print_channels: ('inspect channels, implies -i.', 'flag', 'c'),
        print_days: ('inspect dates and per-day time coverage, implies -i.', 'flag', 'd'),
        print_programs: ('inspect programs. implies -i', 'flag', 'p'),
        filter_channels: ('filter by channels id (comma separated)', 'option', 'C'),
        filter_channels_file: ('filter by channels id loading channels from the file (one per line)', 'option', 'f'),
	filter_date: ('filter by date and time', 'option', 'j'),
        shift_time_onwards: ('shift the start time dates onwards. Accepts time definitions as: 1d, 3M, 6y, 4w.','option','s'),
        shift_time_backwards: ('shift the start time dates backwards. Accepts time definitions as --shift-time-onwards.','option','S'),
        utc: ('normalize start time to UTC','flag','u'),
        print_duration: ('print program duration instead of stop time when possible', 'flag', 't'),
        *xmltv_files):
    """
    Utility to inspect and manipulate XMLTV files.

    If -i, -c or -d are used, a summary of the input files is printed. Otherwise a resulting processed XMLTV is printed.

    Input files are merged into one before processing and printed as a valid merged XMLTV file.
    """

    filter_channels_list = list()

    # Parameters

    if len(xmltv_files) == 0:
        print_warning("No files provided. Exiting.")
        return

    if inspect:
        print_channels = True
        print_days = True

    if filter_channels:
        filter_channels_list = [f.strip() for f in  filter_channels.split(',')]	

    if filter_channels_file:
        try:
            with io.open(filter_channels_file, encoding='utf-8') as filter_channels_f:
                for channel in filter_channels_f:
                    filter_channels_list.append(channel.strip())
        except FileNotFoundError:
            print_warning('Channels filter file does not exist')
            return
        filter_channels=True

    if debug and filter_channels:
        print("Filtering channels:")
        for channel in filter_channels_list:
            print(channel)

    time_delta = None
    time = dict()
    time['d'] = 0
    time['M'] = 0
    time['y'] = 0
    time['w'] = 0
    time['h'] = 0
    time['m'] = 0
    time['s'] = 0

    if shift_time_onwards:
        time_transformations = [t.strip() for t in shift_time_onwards.split(' ')]
        for transform in time_transformations:
            unit = transform[-1]
            if unit in time:
                time[unit] = int(transform[0:len(transform)-1])
            else:
                print_warning('Ignoring malformed time shift: ' + transform)

    if shift_time_backwards:
        time_transformations = [t.strip() for t in shift_time_backwards.split(' ')]
        for transform in time_transformations:
            unit = transform[-1]
            if unit in time:
                time[unit] = time[unit] - int(transform[0:len(transform)-1])
            else:
                print_warning('Ignoring malformed time shift: ' + transform)

    # Colapse years into days
    time['d'] = time['y']*365

    time_delta = timedelta(time['d'], time['s'], 0, 0, time['m'], time ['h'], time['w'])

    # Input

    # xmltv = ET.parse(xmltv_files[0], XMLParser(encoding='utf-8')).getroot()
    xmltv = ET.parse(xmltv_files[0]).getroot()
    for xmltv_file in xmltv_files[1:]:
        one_xmltv = ET.parse(xmltv_file).getroot()
        for elem in one_xmltv:
            if elem.tag == 'programme':
                xmltv_add_program(xmltv, elem)
            if elem.tag == 'channel':
                xmltv_add_channel(xmltv, elem)

    # Process

    if filter_channels:
        for channel_elem in xmltv.findall('./channel'):
            if 'id' in channel_elem.attrib:
                if channel_elem.attrib['id'] not in filter_channels_list:
                    xmltv.remove(channel_elem)
            else:
                print_warning('channel element without id ' + channel_elem.tostring())
        for programme_elem in xmltv.findall('./programme'):
            if 'channel' in programme_elem.attrib:
                if programme_elem.attrib['channel'] not in filter_channels_list:
                    xmltv.remove(programme_elem)
            else:
                print_warning('programme element without id ' + programme_elem.tostring())

    if filter_date:
        for programme_elem in xmltv.findall('./programme'): 
            date_string = (filter_date + ' +0100')
            if 'start' in programme_elem.attrib:
                if programme_elem.attrib['start'] >= date_string and programme_elem:
                    xmltv.remove(programme_elem)
            else:
                print_warning('programme element without id ' + programme_elem.tostring())


    if shift_time_onwards or shift_time_backwards:
        for programme_elem in xmltv.findall('./programme'):
            start = parse_time(programme_elem.attrib['start'])
            stop = parse_time(programme_elem.attrib['stop'])
            start = start + time_delta
            stop = stop + time_delta
            programme_elem.attrib['start'] = encode_time(start)
            programme_elem.attrib['stop'] = encode_time(stop)

    if utc:
        for programme_elem in xmltv.findall('./programme'):
            start = parse_time(programme_elem.attrib['start'])
            stop = parse_time(programme_elem.attrib['stop'])
            programme_elem.attrib['start'] = encode_time(start.astimezone(pytz.utc))
            programme_elem.attrib['stop'] = encode_time(stop.astimezone(pytz.utc))


    # Output

    if print_channels:
            do_print_channels(xmltv)

    if print_days:
            do_print_days(xmltv)

    if print_programs:
            do_print_programs(xmltv, print_duration)
	
    if not print_days and not print_channels and not print_programs:
       print(ET.tostring(xmltv, pretty_print=True).decode('utf-8'))

if  __name__ == '__main__':
    try:
        import plac; plac.call(main)
#    except (FileNotFoundError, ValueError) as e:
    except FileNotFoundError as e:
        print(e)
    except IsADirectoryError as e:
        print(e)

