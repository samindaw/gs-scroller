from __future__ import division, unicode_literals

import re

import lxml.html

from flask import Flask, url_for, abort, render_template

from util import ( Base64Converter, DigitsConverter, DigitListConverter,
    temporary_cache )
import urlread

GOOGLE_TIMEOUT=30

app = Flask(__name__)

app.url_map.converters['base64'] = Base64Converter
app.url_map.converters['digits'] = DigitsConverter
app.url_map.converters['digitlist'] = DigitListConverter


@app.route('/')
def default():
    return render_template('default.html')

@app.route('/e/<base64:sid>/<digits:gid>/<options>')
def sheet_e_opt(sid, gid, options):
    # print('/e/<base64:sid>/<digits:gid>/<options>')
    return sheet_opt(sid, gid, options)
 
@app.route('/e/<base64:sid>/<digits:gid>')
def sheet_e(sid, gid):
    # print('/e/<base64:sid>/<digits:gid>')
    return sheet(sid="e/"+sid, gid=gid)

@app.route('/<base64:sid>/<digits:gid>/<options>')
def sheet_opt(sid, gid, options):
    # print('/<base64:sid>/<digits:gid>/<options>')
    return convert_google_sheet(sid, gid, options)

@app.route('/<base64:sid>/<digits:gid>')
def sheet(sid, gid):
    # print('/<base64:sid>/<digits:gid>')
    return convert_google_sheet(sid, gid,"")

@app.route('/e/<base64:sid>/')
def spreadsheet_e(sid):
    # print('/e/<base64:sid>/')
    return spreadsheet(sid="e/"+sid)

@app.route('/<base64:sid>/')
def spreadsheet(sid):
    # print('/<base64:sid>/')
    title, sheets = google_spreadsheet_data(sid)
    if not sheets:
        raise GoogleSpreadsheetNotFound()
    return render_template('spreadsheet.html', title=title, links=True,
        sid=sid, sheets=sheets, )

@app.route('/e/<base64:sid>/(<digitlist:gids>)')
def spreadsheet_selection_e(sid, gids):
    # print('/e/<base64:sid>/(<digitlist:gids>)')
    return spreadsheet_selection(sid="e/"+sid, gids=gids)

@app.route('/<base64:sid>/(<digitlist:gids>)')
def spreadsheet_selection(sid, gids):
    # print('/<base64:sid>/(<digitlist:gids>)')
    try:
        title, sheets = google_spreadsheet_data(sid)
    except GoogleSpreadsheetNotResponding as error:
        error.sid = error.gid = None
        raise
    gids = set(gids)
    sheets = [ sheet
        for sheet in sheets
        if sheet['gid'] in gids ]
    if not sheets:
        raise GoogleSpreadsheetNotFound()
    return render_template('spreadsheet.html', title=title, links=False,
        sid=sid, sheets=sheets, )

# @temporary_cache(60*5)
def convert_google_sheet(sid, gid, options):
    html = parse_google_document(
        'https://docs.google.com/spreadsheets/d/{sid}/htmlembed/sheet?gid={gid}&{options}'
            .format(sid=sid, gid=gid, options=options),
        errhelp={'sid' : sid, 'gid' : gid} )
    for script in html.iter('script'):
        v = script.get('src')
        if v is None:
            #pass #script.getparent().remove(script)
            script.text = script.text.replace("CHARTS_EXPORT_URI.push('","CHARTS_EXPORT_URI.push('https://docs.google.com")
        else:
            script.set('src',"https://docs.google.com"+v)
        
    html.find('head/link').rewrite_links(
        lambda s: 'https://docs.google.com' + s )
    html.find('head').append(lxml.html.Element( 'link',
        rel='stylesheet', href=url_for('static', filename='metatable.css'),
    ))
    html.find('body').append(lxml.html.Element( 'script',
        src="https://ajax.googleapis.com/ajax/libs/jquery/3.1.1/jquery.min.js"
    ))
    html.find('body').append(lxml.html.Element( 'script',
        src=url_for('static', filename='metatable.js')
    ))
    script = lxml.html.Element('script')
    script.text = ( "$(init); "
        "function init() { "
            "$('body').css('overflow', 'hidden'); "
            "var $table = $('#sheets-viewport table').detach(); "
            "var $metatable = create_metatable($table); "
            "$('body').empty().append($metatable); "
            "$metatable.resize(); "
        " }" 
        "$('.row-header-wrapper').remove();"  
        #"$('td').css('min-width', '100px');"
        "$(window).bind('load', function() {"
        "i=1;"
        "tableWidth=0;"
        "while (true) {  idStr = '#0C'+i.toString(); obj = $(idStr); if (obj[0]==undefined) {break;}; wstr=obj[0].style.width.replace('px', ''); tableWidth+=parseInt(wstr); i++; }"
        "tblList = $('table.waffle');"
        "tblList[1].style.width=tableWidth.toString()+'px';"   
        "tblList[3].style.width=tableWidth.toString()+'px';"   
        "initCharts();"

        "});"
        )
    html.find('body').append(script)
    # with open("output.txt", "w") as text_file:
    #     text_file.write(lxml.html.tostring(html, encoding='utf-8'))
    
    return b'<!DOCTYPE html>\n<meta charset="UTF-8">\n' + \
        lxml.html.tostring(html, encoding='utf-8')

SHEET_PATTERN = re.compile(
    r'{[^{}]*'
        r'name: "(?P<name>[^"]+)"'
    r'[^{}]*'
        r'gid: "(?P<gid>\d+)"'
    r'[^{}]*}' )
# @temporary_cache(60*5)
def google_spreadsheet_data(sid):
    html = parse_google_document(
        'https://docs.google.com/spreadsheets/d/{sid}/pubhtml?widget=true'
            .format(sid=sid),
        errhelp={'sid' : sid} )

    title = html.find('head/title').text
    sheets = []
    for script in html.iter('script'):
        if script.text is None:
            continue
        for match in SHEET_PATTERN.finditer(script.text):
            sheets.append(match.groupdict())
        if sheets:
            break
    return title, sheets

PARSER = lxml.html.HTMLParser(encoding="utf-8")
def parse_google_document(url, errhelp=None, parser=PARSER):
    try:
        # print(url)
        reply_text = urlread.urlread(url, timeout=GOOGLE_TIMEOUT)
    except urlread.NotFound:
        raise GoogleSpreadsheetNotFound(errhelp)
    except urlread.NotResponding:
        raise GoogleSpreadsheetNotResponding(errhelp)
    return lxml.html.fromstring(reply_text, parser=parser)

class GoogleSpreadsheetException(Exception):
    def __init__(self, errhelp=None):
        super(GoogleSpreadsheetException, self).__init__(self)
        if errhelp is not None:
            self.sid = errhelp.get('sid')
            self.gid = errhelp.get('gid')
        else:
            self.sid = self.gid = None

class GoogleSpreadsheetNotFound(GoogleSpreadsheetException):
    pass

class GoogleSpreadsheetNotResponding(GoogleSpreadsheetException):
    pass

@app.errorhandler(GoogleSpreadsheetNotFound)
def sheet_not_found(exception):
    return render_template('google-404.html'), 404

@app.errorhandler(GoogleSpreadsheetNotResponding)
def sheet_timeout(exception):
    return render_template('google-504.html', sid=exception.sid, gid=exception.gid), 504

@app.errorhandler(404)
def not_found(exception):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)

