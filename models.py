"""Models used by the maintenance NApp.

This module define models for the maintenance window itself and the
scheduler.
"""
import datetime
from uuid import uuid4

import pytz
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler

from kytos.core import log
from kytos.core.interface import TAG, UNI
from kytos.core.link import Link

TIME_FMT = "%Y-%m-%dT%H:%M:%S%z"


class MaintenanceWindow:
    """Class to store a maintenance window."""

    def __init__(self, start, end, controller, **kwargs):
        """Create an instance of MaintenanceWindow.

        Args:
            start(datetime): when the maintenance will begin
            end(datetime): when the maintenance will finish
            items: list of items that will be maintained;
                each item can be either a switch, a link or a client interface
        """
        # pylint: disable=invalid-name
        items = kwargs.get('items')
        if items is None:
            items = list()
        mw_id = kwargs.get('mw_id')
        self.id = mw_id if mw_id else uuid4().hex
        self.start = start
        self.end = end
        self.items = items
        self.controller = controller

    def as_dict(self):
        """Return this maintenance window as a dictionary."""
        mw_dict = dict()
        mw_dict['id'] = self.id
        mw_dict['start'] = self.start.strftime(TIME_FMT)
        mw_dict['end'] = self.end.strftime(TIME_FMT)
        mw_dict['items'] = []
        for i in self.items:
            try:
                mw_dict['items'].append(i.as_dict())
            except (AttributeError, TypeError):
                mw_dict['items'].append(i)
        return mw_dict

    @classmethod
    def from_dict(cls, mw_dict, controller):
        """Create a maintenance window from a dictionary of attributes."""
        mw_id = mw_dict.get('id')

        start = cls.str_to_datetime(mw_dict['start'])
        end = cls.str_to_datetime(mw_dict['end'])
        items = cls.get_items(mw_dict['items'], controller)
        return cls(start, end, controller, items=items, mw_id=mw_id)

    def update(self, mw_dict, controller):
        """Update a maintenance window with the data from a dictionary."""
        if 'start' in mw_dict:
            self.start = self.str_to_datetime(mw_dict['start'])
        if 'end' in mw_dict:
            self.end = self.str_to_datetime(mw_dict['end'])
        if 'items' in mw_dict:
            self.items = self.get_items(mw_dict['items'], controller)

    @staticmethod
    def intf_from_dict(intf_id, controller):
        """Get the Interface instance with intf_id."""
        intf = controller.get_interface_by_id(intf_id)
        return intf

    @staticmethod
    def uni_from_dict(uni_dict, controller):
        """Create UNI instance from a dictionary."""
        intf = MaintenanceWindow.intf_from_dict(uni_dict['interface_id'],
                                                controller)
        tag = TAG.from_dict(uni_dict['tag'])
        if intf and tag:
            return UNI(intf, tag)
        return None

    @staticmethod
    def link_from_dict(link_dict, controller):
        """Create a link instance from a dictionary."""
        endpoint_a = controller.get_interface_by_id(
            link_dict['endpoint_a']['id'])
        endpoint_b = controller.get_interface_by_id(
            link_dict['endpoint_b']['id'])

        link = Link(endpoint_a, endpoint_b)
        if 'metadata' in link_dict:
            link.extend_metadata(link_dict['metadata'])
        s_vlan = link.get_metadata('s_vlan')
        if s_vlan:
            tag = TAG.from_dict(s_vlan)
            link.update_metadata('s_vlan', tag)
        return link

    @staticmethod
    def str_to_datetime(str_date):
        """Convert a string representing a date and time to datetime."""
        date = datetime.datetime.strptime(str_date, TIME_FMT)
        return date.astimezone(pytz.utc)

    @staticmethod
    def get_items(item_list, controller):
        """Convert a list of items to the right types."""
        return_list = []
        for i in item_list:
            try:
                item = MaintenanceWindow.uni_from_dict(i, controller)
            except KeyError:
                item = MaintenanceWindow.link_from_dict(i, controller)
            except TypeError:
                item = i
            if item:
                return_list.append(item)
        return return_list

    def start_mw(self):
        """Actions taken when a maintenance window starts."""
        pass

    def end_mw(self):
        """Actions taken when a maintenance window finishes."""
        pass


class Scheduler:
    """Scheduler for a maintenance window."""

    def __init__(self):
        """Initialize a new scheduler."""
        self.scheduler = BackgroundScheduler(timezone=pytz.utc)
        self.scheduler.start()

    def add(self, maintenance):
        """Add jobs to start and end a maintenance window."""
        self.scheduler.add_job(maintenance.start_mw, 'date',
                               id=f'{maintenance.id}-start',
                               run_date=maintenance.start)
        self.scheduler.add_job(maintenance.end_mw, 'date',
                               id=f'{maintenance.id}-end',
                               run_date=maintenance.end)

    def remove(self, maintenance):
        """Remove jobs that start and end a maintenance window."""
        try:
            self.scheduler.remove_job(f'{maintenance.id}-start')
        except JobLookupError:
            log.info(f'Job to start {maintenance.id} already removed.')
        try:
            self.scheduler.remove_job(f'{maintenance.id}-end')
        except JobLookupError:
            log.info(f'Job to end {maintenance.id} already removed.')