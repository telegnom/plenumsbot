#!/usr/bin/env python

import os
import re
import sys
import json
import datetime
from jinja2 import Template
import dokuwiki


class WikiError(Exception):
    pass


class Wiki:
    def __init__(self, url, wikiuser, wikipass):
        try:
            self.wiki = dokuwiki.DokuWiki(url, wikiuser, wikipass)
        except dokuwiki.DokuWikiError:
            raise WikiError("An error occured while connecting to the wiki.")

    def get_page(self, page):
        """ returns the contents of a given page """
        try:
            return self.wiki.pages.get(page)
        except dokuwiki.DokuWikiError as err:
            print(f"An error occurred while receiving the page {page}. Error: {err}")
            sys.exit(1)

    def get_page_versions(self, page):
        """ returns a list of the last versions of a given page """
        try:
            return self.wiki.pages.versions(page)
        except dokuwiki.DokuWikiError as err:
            print(
                f"An error occurred while receiving the versions of the page {page}: {err}"
            )
            sys.exit(1)

    def get_page_info(self, page):
        """ return meta information about a given page """
        try:
            return self.wiki.pages.info(page)
        except dokuwiki.DokuWikiError as err:
            print(
                f"An error occurred while receiving informations of the page {page}: {err}"
            )
            sys.exit(1)

    def page_exists(self, page):
        """ returns True if a given page exists, False if not """
        page_info = self.get_page_info(page)
        if "name" in page_info and page_info["name"] == page:
            return True

        return False

    def set_page(self, page, content, summary="modified by plenumsbot"):
        """ writes content to a given page """
        try:
            self.wiki.pages.set(page, content, sum=summary)
        except dokuwiki.DokuWikiError as err:
            print(f"An error occurred while writing the page {page}: {err}")
            sys.exit(1)
        return True

    def set_redirect(self, redirect_src, redirect_dest):
        """ set a redirect from redirect_src to redirect_dest """
        redirect_content = f"~~GOTO>{redirect_dest}~~"
        self.set_page(
            redirect_src, redirect_content, f"redirect target set to {redirect_dest}"
        )


class Plenum:
    def __init__(
        self, dow, namespace, tpl_plenum, tpl_blank, today=datetime.date.today()
    ):
        self.dow = dow
        self.next_date = self._calc_next_date(today)
        self.last_date = self._calc_last_date(today)
        self.next_page = ":".join([namespace, self.next_date.strftime("%Y-%m-%d")])
        self.last_page = ":".join([namespace, self.last_date.strftime("%Y-%m-%d")])
        try:
            with open(tpl_plenum, "r") as fh:
                self.tpl_plenum = fh.read()
        except BaseException as e:
            print(f"unable to load plenum template: {e}")

        try:
            with open(tpl_blank, "r") as fh:
                self.tpl_blank = fh.read()
        except BaseException as e:
            print(f"unable to load plenum blank topics template: {e}")

    def _calc_next_date(self, today):
        # today = datetime.date.today()
        delta_days = self.dow - today.weekday()
        if delta_days <= 0:
            delta_days += 7
        return today + datetime.timedelta(delta_days)

    def _calc_last_date(self, today):
        # today = datetime.date.today()
        delta_days = self.dow - today.weekday()
        if delta_days > 0:
            delta_days -= 7
        return today + datetime.timedelta(delta_days)

    def last_plenum_took_place(self, plenum_page):
        page_lines = plenum_page.splitlines()
        match = re.search(
            r"^Ende:\s*\d{2}:\d{2}\s*Uhr\s*$",
            "\n".join(page_lines[-2:]),
            re.MULTILINE | re.IGNORECASE,
        )
        return bool(match)

    def upcoming_events(self, plenum_page):
        """ find upcoming events in plenum_page which are after the next plenum """
        # find section termine
        plenum_page_list = plenum_page.splitlines()
        events_heading = re.findall(
            r"^(\s*={5}\s*Termine\s*={5}\s*)$",
            plenum_page,
            re.MULTILINE | re.IGNORECASE,
        )

        # return False if heading "Termine" not in page content
        if not events_heading:
            return False
        events_heading = events_heading[0].strip("\n")
        events_begin = plenum_page_list.index(events_heading) + 1

        eventlist = []
        for line in plenum_page_list[events_begin:]:
            # 1st capture group = date, 2nd = event description
            event = re.findall(r"^\s{2,4}\*\s(\d{4}-\d{2}-\d{2})(.*)$", line)
            if event and event[0][0] > self.next_date.strftime("%Y-%m-%d"):
                eventlist.append(event[0])

        return eventlist

    def extract_content(self, plenum_page):
        pagelist = plenum_page.splitlines()
        section_index = []
        for i in range(0, len(pagelist)):
            if re.match(r"^={5}[^=]*={5}$", pagelist[i].strip()):
                section_index.append(i)
        section_index.append(len(pagelist) - 1)
        sections = []
        for idx in section_index:
            if section_index.index(idx) != len(section_index) - 1:
                sections.append((idx, section_index[section_index.index(idx) + 1] - 1))

        section_list = []

        for section in sections:
            headline = pagelist[section[0]].strip("=").strip()
            content = "\n".join(pagelist[section[0] + 1 : section[1]])
            section_list.append((headline, content))

        return section_list

    def generate_page_next_plenum(self, plenum_page):
        # checking if last plenum took place
        if self.last_plenum_took_place(plenum_page):

            # last plenum took place
            content = self.tpl_blank

        else:
            # last plenum didn't take place
            # extract topics from last plenum
            contentlist = self.extract_content(plenum_page)
            content = ""
            for block in contentlist:
                if block[0] == "Termine":
                    continue
                content += "\n".join(
                    [f"===== {block[0]} =====", block[1].strip("\n"), "\n"]
                )
            content = content.strip()

        # processing events
        events = ""
        eventlist = self.upcoming_events(plenum_page)
        if eventlist:
            for event in eventlist:
                events += f"  * {event[0]}{event[1]}\n"
        else:
            eventlist = ""

        # generate new page from template
        template = Template(self.tpl_plenum)
        return template.render(
            date_plenum=self.next_date, upcoming_events=events, content=content
        )

    def update_index_page(self, index_page, namespace):
        plenum_list = index_page.splitlines()

        try:
            insert_index = plenum_list.index(f"===== {self.next_date.year} =====") + 1
        except ValueError as err:
            # print("Year not found")
            insert_index = None

        try:
            protocol_index = plenum_list.index("====== Protokolle ======") + 1
        except ValueError as err:
            # print("Protokolle not found in index page")
            protocol_index = 0

        if not insert_index:
            insert_index = protocol_index + 2
            plenum_list.insert(protocol_index, f"===== {self.next_date.year} =====")

        plenum_list.insert(insert_index, f"  * [[{ self.next_page }]]")
        return "\n".join(plenum_list)

    def plenum_in_list(self, plenum_page):
        """ Returns True if self.next_page is found in plenum_page.
            Used to prevent double entries in the list of plenums """
        finding = plenum_page.find(self.next_page)
        if finding >= 0:
            return True
        else:
            return False


def load_config(owndir):
    """load config from config.(local.)json"""
    config_file = os.path.join(owndir, "config.json")
    with open(config_file, "r") as fh:
        try:
            config = json.load(fh)
        except BaseException as e:
            print(f"While loading configuration file an error occurred: {e}")
            sys.exit(1)

    local_config_file = os.path.join(owndir, "config.local.json")
    if os.path.isfile(local_config_file):
        with open(local_config_file, "r") as fh:
            try:
                local_config = json.load(fh)
            except BaseException as e:
                print(f"While loading local configuration file an error occurred: {e}")
                sys.exit(1)
    config = {**config, **local_config}
    return config


if __name__ == "__main__":
    # load configuration
    owndir = os.path.dirname(os.path.realpath(__file__))
    config = load_config(owndir)
    # setup plenum and wiki objects
    plenum = Plenum(
        config["plenum_day_of_week"],
        config["namespace"],
        os.path.join(owndir, "template_plenum.j2"),
        os.path.join(owndir, "template_blank_topics.j2"),
    )
    try:
        wiki = Wiki(config["wiki_url"], config["wiki_user"], config["wiki_password"])
        last_page_content = wiki.get_page(plenum.last_page)
        index_page_content = wiki.get_page(config["indexpage"])
        new_page_content = plenum.generate_page_next_plenum(last_page_content)
        new_index_page_content = plenum.update_index_page(
            index_page_content, config["namespace"]
        )
        wiki.set_page(plenum.next_page, new_page_content)
        if not plenum.plenum_in_list(index_page_content):
            wiki.set_page(config["indexpage"], new_index_page_content)
        wiki.set_redirect(config["redirectpage"], plenum.next_page)
    except WikiError as err:
        sys.exit(err)