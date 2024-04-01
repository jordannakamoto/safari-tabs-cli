# Safari Tabs Picker CLI
# Lets the user view and switch between open tabs
# f - to focus window
# holding . toggles details
# ? - to copy address

# ISSUE
# Need to implement curses mouse and scroll control...


# FEATURE TODO
#2. Tab Decay and Cleanup
# Description: Tabs that haven't been accessed in a while "decay" visually in the list, perhaps by changing color or fading. After a certain period, suggest or automatically close decayed tabs to keep things tidy.
# Implementation: Track the last access time for each tab. As part of the display logic, modify the appearance of tab entries based on how long ago they were last accessed. Offer a cleanup command to close all decayed tabs.

# 4. Gamification of Tab Management
# Description: Introduce a points system for opening, organizing, and closing tabs. Users can "level up" based on their tab management efficiency.
# Implementation: Assign points for various actions (e.g., closing old tabs, organizing tabs into groups). Track user progress and display a "score" or "level" in the CLI. Offer rewards like custom themes or unlocking advanced features.

# 5. Shared Tab Sessions
# Description: Allow users to share a session of tabs with others, creating a synchronized tab list that can be viewed and modified by all participants.
# Implementation: Develop a simple server-client model where one CLI instance can host a session, and others can connect to it. Use a combination of websockets and HTTP to synchronize tab lists between participants.

# 9. Tab Time Travel
# Description: Allow users to "go back in time" to see what tabs were open at different points in the past, providing a way to recover lost tabs or revisit past research.
# Implementation: Periodically snapshot the current state of open tabs and store these snapshots in a history log. Provide a way to browse through these snapshots and restore tabs from them.

# Tab Garden: Create a virtual garden where each tab represents a plant or flower. Users can nurture their tabs by watering them (opening them) regularly and watching them grow over time.

# Idea... some function for sleeping the app or various features


import curses
import subprocess
import string
import re  # Import regular expressions for URL parsing
import time
import json  # Add this import
import sqlite3
import os

#- DATA  ----------------------------------------------------------------#
closed_tabs_stack = []    # Closed Tabs for Undo History
tab_create_times = {}     # Dictionary to store start times for each tab
tab_start_times   = {}    # Dictionary to store the last start times for each tab
tab_active_times  = {}    # Dictionary to store time active for each tab
#========================================================================#

def run_applescript(script):
    return subprocess.run(['osascript', '-e', script], capture_output=True, text=True)

# TODO: implement pinging in background thread...
# def run_applescript_background(script):
#     subprocess.Popen(['osascript', '-e', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ~~~ APPLESCRIPTS ~~~  -------------------------------------------------#
def get_safari_tabs():
    script = '''
    set output to "["
    tell application "Safari"
        set firstTab to true
        repeat with aWindow in windows
            repeat with aTab in tabs of aWindow
                if firstTab then
                    set firstTab to false
                else
                    set output to output & ", "
                end if
                set tabTitle to name of aTab
                set tabUrl to URL of aTab
                set output to output & "{\\"title\\": \\"" & tabTitle & "\\", \\"url\\": \\"" & tabUrl & "\\"}"
            end repeat
        end repeat
    end tell
    return output & "]"
    '''
    return run_applescript(script)

# Get currently active tab
def get_active_safari_tab():
    script = '''
    tell application "Safari"
        set output to "{}"
        if (count of windows) > 0 then
            set frontWindow to front window
            set currentTab to current tab of frontWindow
            set tabTitle to name of currentTab
            set tabUrl to URL of currentTab
            set output to "{\\"title\\": \\"" & tabTitle & "\\", \\"url\\": \\"" & tabUrl & "\\"}"
        end if
        return output
    end tell
    '''
    return run_applescript(script)

def reopen_last_closed_tab():
    global closed_tabs_stack
    
    if closed_tabs_stack:
        last_closed_url = closed_tabs_stack.pop()  # Pop the last closed URL from the stack
        script = f'''
        tell application "Safari"
            tell window 1
                set newTab to make new tab with properties {{URL: "{last_closed_url}"}}
                set current tab to newTab
            end tell
        end tell
        '''
        run_applescript(script)

def close_current_safari_tab():
# Fetch the URL of the tab before closing, to save it for undo
    get_url_script = f'''
    tell application "Safari"
        tell front window
            get URL of current tab
        end tell
    end tell
    '''
    result = run_applescript(get_url_script)
    if result.stdout:
        closed_tabs_stack.append(result.stdout.strip())  # Push the URL onto the stack
    script = f'''
        tell application "Safari"
            tell front window
                close current tab
            end tell
        end tell
    '''
    run_applescript(script)

def activate_safari():

    script = '''
    tell application "System Events"
        tell process "Safari"
            set frontmost to true
        end tell
    end tell
    '''
    return run_applescript(script)

# Manage Safari Tab - select or close tab!
def manage_safari_tab(tab_letter, close_tab=False):

    global closed_tabs_stack
    global tab_start_times
    global tab_active_times

    # Store the start time when selecting a tab
    if not close_tab:
        tab_start_times[tab_letter] = time.time()

    letter_to_index = dict(zip(string.ascii_lowercase, range(1, 27)))
    tab_index = letter_to_index.get(tab_letter.lower(), 0)  # Ensure lowercase for indexing
    if close_tab:
        # Fetch the URL of the tab before closing, to save it for undo
        get_url_script = f'''
        tell application "Safari"
            URL of tab {tab_index} of window 1
        end tell
        '''
        result = run_applescript(get_url_script)
        if result.stdout:
            closed_tabs_stack.append(result.stdout.strip())  # Push the URL onto the stack
        
        # AppleScript to close the tab
        script = f'''
        tell application "Safari"
            close tab {tab_index} of window 1
        end tell
        '''
    else:
        # AppleScript to activate the tab (as before)
        script = f'''
        tell application "Safari"
            set counter to 1
            repeat with aWindow in windows
                repeat with aTab in tabs of aWindow
                    if counter = {tab_index} then
                        set current tab of aWindow to aTab
                        return
                    end if
                    set counter to counter + 1
                end repeat
            end repeat
        end tell
        '''
    return run_applescript(script)
# ~~~ END APPLESCRIPTS ~~~ ==============================================#

# ---- UI Functions -----------------------------------------------------#
def ui_show_tabs_full(stdscr, tabs):
    stdscr.clear()

    for idx, tab in enumerate(tabs, start=1):
        # Terminal Dimensions Check
        max_y, max_x = stdscr.getmaxyx()  
        if idx >= max_y:
            break  
        # Stop if we've reached the bottom of the terminal
        # ...

        # Remove content within parentheses from the title
        tab_title = re.sub(r'\(\d+\)', '', tab['title']).strip()

        # Processing URL to remove protocol, www, and .com
        tab_url = re.sub(r"https?://(?:www\.)?", "", tab['url'])
        tab_url = re.sub(r"\.com.*", "", tab_url)
        tab_url = tab_url.split('/')[0]

        # Construct display string with full title
        display_str = f"{string.ascii_lowercase[idx-1]}: {tab_title} - {tab_url}\n"
        stdscr.addstr(display_str)
    stdscr.refresh()

def ui_show_tabs(stdscr, tabs, show_times=False):
    stdscr.clear()
    current_time = time.time()  # Fetch the current time for calculating ongoing durations

    for idx, tab in enumerate(tabs, start=1):
        # Terminal Dimensions Check
        max_y, max_x = stdscr.getmaxyx()  
        if idx >= max_y:
            break  
        # Stop if we've reached the bottom of the terminal
        # ...

        tab_title = tab['title']
        
        # Use regular expressions to remove patterns like (13) from the title
        # This pattern targets parentheses enclosing numbers
        tab_title = re.sub(r'\(\d+\)', '', tab_title).strip()

        CL = 13 # Cutoff Length

        # Check if limiting to CL characters cuts off a word
        if len(tab_title) > CL:
            if tab_title[CL-1].isspace() or tab_title[CL].isspace():
                # If the CLth character or the one after is a space, don't need to adjust
                shortened_title = tab_title[:CL]
            else:
                # Find the last space within the first CL characters to avoid cutting off a word
                last_space = tab_title[:CL].rfind(' ')
                shortened_title = tab_title[:last_space] + ' ' * (CL - last_space)
        else:
            # If the title is shorter than or equal to CL characters, use it directly
            shortened_title = tab_title + ' ' * (CL - len(tab_title))  # Pad with spaces if shorter

        
        # OR Limit to first 2 words
        # tab_title_words = tab_title.split()[:2]
        # shortened_title = ' '.join(tab_title_words)
            
        if tab['url'] != "missing value":
            tab_url = re.sub(r"https?://(?:www\.)?", "", tab['url'])  # Remove protocol and www
            tab_url = re.sub(r"\.com.*", "", tab_url)  # Remove .com and everything after
            tab_url = tab_url.split('/')[0]  # Keep only the domain
        else:
            tab_url = ""
        
        # TRY ADDDING THE DISPLAY STR
        try:
            display_str = f"{string.ascii_lowercase[idx-1]}: {shortened_title} - {tab_url}"
            # TODO 2: Active Tab Decoration... First I need to push the updater to tab list the background so we don't call it unless there are changes I guess...
            # active_tab_index = get_active_tab_index()  # Function to get the index of the active tab
            # # Check if this tab is active and adjust the display accordingly
            # display_str = f">{shortened_title} - {tab_url}\n" if idx == active_tab_index else f"{string.ascii_lowercase[idx-1]}: {shortened_title} - {tab_url}\n"
        except curses.error as e:
            display_str = "address loading..."
        # OPTION FOR SHOWING TIME ACTIVE
        if show_times:
            # Initialize active_time_seconds to 0
            active_time_seconds = 0
            if tab['url'] in tab_start_times:  # If the tab is currently being tracked
                # Calculate ongoing duration for currently active tab
                # TODO: Analyze if this time is gathered efficiently
                active_time_seconds = current_time - tab_start_times[tab['url']]
            if tab['url'] in tab_active_times:  # If the tab has accumulated active time
                active_time_seconds += tab_active_times.get(tab['url'], 0)

            formatted_duration = format_duration(active_time_seconds)
            # Append the duration to the tab's display information
            display_str += f" [{formatted_duration}]"        
        try:
            display_str += "\n"
            stdscr.addstr(display_str)
        except curses.error as e:
            # Handling potential error due to terminal window size
            pass
    stdscr.refresh()

# UI Helpers ------------------------------------- #
def ui_print_header(stdscr):
    curses.init_pair(1, 60, -1)
    stdscr.attron(curses.color_pair(1))
    stdscr.addstr("Safari Tabs\n")
    stdscr.attroff(curses.color_pair(1))

def format_duration(seconds):
    # Converts seconds to a string of the format "Xm Ys" for minutes and seconds
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{int(minutes)}m {int(seconds)}s"

# ===== END UI Functions  ===============================================#

# ---- Search -----------------------------------------------------------#
def perform_search(stdscr, query):
    # Expand the path and connect to the database
    db_path = os.path.expanduser('~/Library/Safari/History.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    is_youtube_query = 'youtube' in query.lower()

    # Your SQL query remains unchanged
    sql_query = """
    SELECT MAX(datetime(visit_time + 978307200, 'unixepoch', 'localtime')) as visit_date, title, url
    FROM history_items
    INNER JOIN history_visits ON history_items.id = history_visits.history_item
    WHERE url LIKE ? OR title LIKE ?
    GROUP BY url
    ORDER BY visit_time DESC
    """
    cursor.execute(sql_query, ('%' + query + '%', '%' + query + '%'))

    # Fetch all results and close the database connection
    results = cursor.fetchall()
    cursor.close()
    conn.close()

    # Initialize the offset for scrolling
    offset = 0

    # Enable mouse input
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "Search results for: " + query + "\n\n")

        # Properly calculate the maximum number of results to display
        max_y, max_x = stdscr.getmaxyx()
        max_results = max_y - 3  # Adjusted for prompt space

        # Iterate over a slice of results based on the current offset
        for idx, row in enumerate(results[offset:offset + max_results]):
            # Prepare the display string for each result
            visit_date, title, url = row
            if is_youtube_query:
                title = re.sub(r'\(\d+\)', '', title).strip()
            display_str = f"{title} - {url}"
            safe_width = max(max_x - 2, 1)  # Ensure the width is at least 1
            display_str = display_str[:safe_width]  # Truncate to fit the width
            
            # Attempt to display the string, catching any curses errors
            try:
                stdscr.addstr(idx + 2, 0, display_str)
            except curses.error:
                pass  # Ignore errors, which are likely due to boundary issues


        stdscr.addstr(stdscr.getmaxyx()[0] - 1, 0, "Press b to return... 'j' down, 'k' up")

        stdscr.refresh()

        # Handle input
        # Inside your while loop in perform_search function
        ch = stdscr.getch()
        # Remove or comment out if ch == curses.KEY_MOUSE block
        if ch == ord('b') or ch == curses.KEY_EXIT:  # Exit the search
            break
        elif ch == ord('k') and offset > 0:  # Scroll up
            offset -= 1
        elif ch == ord('j') and offset < len(results) - max_y:  # Scroll down
            offset += 1
# ===== END Search  =====================================================#
            
#------------------------------------------------------------------------@
#       MAIN
#------------------------------------------------------------------------@
def main_loop(stdscr):
    ## Init Curses 
    curses.start_color()
    curses.use_default_colors()
    curses.curs_set(0)  # Hide the cursor for a cleaner display

    #- FLAGS -#
    fSearchMode          = False           # Manage control flow for normal vs search mode
    fShowFullTitle       = False       # Toggle Display: full tab title
    fShowTabTimeActive   = False  # Toggle Display: how much time each tab has been open
    #=========#
    #- DATA --#
    activeTab = {'title': '', 'url': ''}
    search_query = ""
    #---------#

    # Start Main Loop #
    while True:
        stdscr.clear()
        ui_print_header(stdscr)

        if not fSearchMode: # <------- If we're not in search mode, provide the normal tab browser UI
            global closed_tabs_stack

            # Fetch and process tabs
            result = get_safari_tabs()
            # TODO: Put this in a background process
            if result.returncode == 0 and result.stdout:
                try:
                    active_tab_result = get_active_safari_tab()
                    current_active_tab = json.loads(active_tab_result.stdout)
                except json.JSONDecodeError:
                    stdscr.addstr("Error decoding JSON for active tab\n")
                if current_active_tab != activeTab:
                    # The active tab has changed
                    
                    # SUB PROCEDURE FOR SETTING TIMERS #
                    current_time = time.time()  # Get the current time
                    # Ensure the active tab is in the start times tracking; if not, there's nothing to calculate
                    if activeTab['url'] in tab_start_times:
                        # Calculate the duration this tab has been active by subtracting the start time from the current time
                        duration_active = current_time - tab_start_times[activeTab['url']]

                        # If the tab already has accumulated active time, add to it; otherwise, start fresh
                        if activeTab['url'] in tab_active_times:
                            tab_active_times[activeTab['url']] += duration_active
                        else:
                            tab_active_times[activeTab['url']] = duration_active

                    # Now, update activeTab to the newly active tab before setting its start time
                    activeTab = current_active_tab

                    # Finally, reset the start time for the newly active tab
                    tab_start_times[activeTab['url']] = current_time
                    # END TIMER SUBPROCEDURE #
                try:
                    tabs = json.loads(result.stdout)
                    tabs = tabs[:26]                     #    Limit set to 26 tabs
                    if fShowFullTitle:
                        ui_show_tabs_full(stdscr, tabs)  # 1. Show tabs with full titles if mode has been toggled
                    else:
                        ui_show_tabs(stdscr, tabs, fShowTabTimeActive)       # 2. Show tabs in normal shortened mode
                except json.JSONDecodeError:
                    stdscr.addstr("Error decoding JSON\n")
            else:
                stdscr.addstr("Error fetching tabs\n")

            # START GET USER KEY INPUT ... Non-blocking input with timeout
            stdscr.nodelay(True) # Make getch() non-blocking
            stdscr.timeout(100)  # Reduced timeout for more responsive toggle
            
            ch = stdscr.getch()
            if ch != -1:                                 # If a key was pressed
                if ch == ord('.'):
                    fShowFullTitle = not fShowFullTitle             # .   : toggle ShowFullTitle
                elif 97 <= ch <= 122:                               # a-z : select Safari tab
                    manage_safari_tab(chr(ch), close_tab=False)
                elif 65 <= ch <= 90:                                # A-Z : close Safari tab
                    manage_safari_tab(chr(ch), close_tab=True)
                elif ch == ord('/'):                                # /   : activate Safari window
                    activate_safari()
                elif ch == ord('\''):                               # '   : close active tab
                    close_current_safari_tab()                     
                elif ch == ord(';'):                                # ;   : reopen closed tabs from close history stack
                    reopen_last_closed_tab()
                elif ch == ord(','):                                # ,   : Start Search Mode
                    fSearchMode = True
                elif ch == ord('['):
                    fShowTabTimeActive = not fShowTabTimeActive     # [   : Show Tab Time Spent Active
                elif ch == ord('q'):
                    break  # Exit the loop if 'q' is pressed
        # LOOP FOR SEARCH MODE
        else:
            stdscr.addstr(0, 0, "Enter search query: " + search_query)

        ch = stdscr.getch()
        if ch == ord(','):
            fSearchMode = not fSearchMode  # Toggle search mode
            search_query = ""  # Reset search query
        elif ch == ord('q') and not fSearchMode:
            break  # Exit if 'q' is pressed and not in search mode
        elif fSearchMode:
            if ch == 10:  # Enter key
                # Perform search with the current query
                perform_search(stdscr, search_query)
                fSearchMode = False  # Exit search mode after search
                stdscr.getch()  # Wait for any key press to return
            elif ch == 127 or ch == 8:  # Handle backspace for search query
                search_query = search_query[:-1]
            elif ch >= 32 and ch <= 126:  # Add printable characters to the query
                search_query += chr(ch)

        stdscr.refresh()
        # time.sleep(0.1)
        

# CONTINUE GLOBAL ---------------------------------------------------- #
# Use curses.wrapper to setup and cleanup the terminal window automatically
curses.wrapper(main_loop)
