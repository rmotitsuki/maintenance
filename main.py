"""Main module of kytos/maintenance Kytos Network Application.

This NApp creates maintenance windows, allowing the maintenance of network
devices (switch, link, and interface) without receiving alerts.
"""
from datetime import datetime, timedelta

import pytz
from flask import jsonify, request
from napps.kytos.maintenance.models import MaintenanceID
from napps.kytos.maintenance.models import MaintenanceWindow as MW
from napps.kytos.maintenance.models import Scheduler, Status
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, NotFound, UnsupportedMediaType

from kytos.core import KytosNApp, rest

TIME_FMT = "%Y-%m-%dT%H:%M:%S%z"


def validate_mw(maintenance: MW):
    """Validates received maintenance windows
    """
    now = datetime.now(pytz.utc)
    if maintenance is None:
        raise BadRequest('One or more items are invalid')
    if maintenance.start < now:
        raise BadRequest('Start in the past not allowed')
    if maintenance.end <= maintenance.start:
        raise BadRequest('End before start not allowed')
    if not maintenance.switches\
        and not maintenance.interfaces\
        and not maintenance.links:
        raise BadRequest('At least one item must be provided')


class Main(KytosNApp):
    """Main class of kytos/maintenance NApp.

    This class is the entry point for this napp.
    """

    def setup(self):
        """Replace the '__init__' method for the KytosNApp subclass.

        The setup method is automatically called by the controller when your
        application is loaded.

        So, if you have any setup routine, insert it here.
        """
        self.scheduler = Scheduler.new_scheduler(self.controller)
        self.scheduler.start()

    def execute(self):
        """Run after the setup method execution.

        You can also use this method in loop mode if you add to the above setup
        method a line like the following example:

            self.execute_as_loop(30)  # 30-second interval.
        """

    def shutdown(self):
        """Run when your napp is unloaded.

        If you have some cleanup procedure, insert it here.
        """
        self.scheduler.shutdown()

    @rest('/v1', methods=['GET'])
    def get_all_mw(self):
        """Return all maintenance windows."""
        maintenances = self.scheduler.list_maintenances()
        return jsonify(maintenances), 200

    @rest('/v1/<mw_id>', methods=['GET'])
    def get_mw(self, mw_id: MaintenanceID):
        """Return one maintenance window."""
        window = self.scheduler.get_maintenance(mw_id)
        if window:
            return jsonify(window.dict()), 200
        raise NotFound(f'Maintenance with id {mw_id} not found')

    @rest('/v1', methods=['POST'])
    def create_mw(self):
        """Create a new maintenance window."""
        data = request.get_json()
        if not data:
            raise UnsupportedMediaType('The request does not have a json')
        try:
            maintenance = MW.parse_obj(data)
        except ValidationError as err:
            raise BadRequest('Failed to create window') from err
        validate_mw(maintenance)
        self.scheduler.add(maintenance)
        return jsonify({'mw_id': maintenance.id}), 201

    @rest('/v1/<mw_id>', methods=['PATCH'])
    def update_mw(self, mw_id: MaintenanceID):
        """Update a maintenance window."""
        data = request.get_json()
        if not data:
            raise UnsupportedMediaType('The request does not have a json')
        old_maintenance = self.scheduler.get_maintenance(mw_id)
        if old_maintenance is None:
            raise NotFound(f'Maintenance with id {mw_id} not found')
        if old_maintenance.status == Status.RUNNING:
            raise BadRequest('Updating a running maintenance is not allowed')
        try:
            new_maintenance = MW.parse_obj({**old_maintenance.dict(), **data})
        except ValidationError as err:
            raise BadRequest('Failed to create window') from err
        validate_mw(new_maintenance)
        self.scheduler.remove(mw_id)
        self.scheduler.add(new_maintenance)
        return jsonify({'response': f'Maintenance {mw_id} updated'}), 200

    @rest('/v1/<mw_id>', methods=['DELETE'])
    def remove_mw(self, mw_id: MaintenanceID):
        """Delete a maintenance window."""
        maintenance = self.scheduler.get_maintenance(mw_id)
        if maintenance is None:
            raise NotFound(f'Maintenance with id {mw_id} not found')
        if maintenance.status == Status.RUNNING:
            raise BadRequest('Deleting a running maintenance is not allowed')
        self.scheduler.remove(mw_id)
        return jsonify({'response': f'Maintenance with id {mw_id} '
                                    f'successfully removed'}), 200

    @rest('/v1/<mw_id>/end', methods=['PATCH'])
    def end_mw(self, mw_id: MaintenanceID):
        """Finish a maintenance window right now."""
        maintenance = self.scheduler.get_maintenance(mw_id)
        if maintenance is None:
            raise NotFound(f'Maintenance with id {mw_id} not found')
        if maintenance.status == Status.PENDING:
            raise BadRequest(
                f'Maintenance window {mw_id} has not yet started'
            )
        if maintenance.status == Status.FINISHED:
            raise BadRequest(
                f'Maintenance window {mw_id} has already finished'
            )
        self.scheduler.end_maintenance_early(mw_id)
        return jsonify({'response': f'Maintenance window {mw_id} '
                                    f'finished'}), 200

    @rest('/v1/<mw_id>/extend', methods=['PATCH'])
    def extend_mw(self, mw_id):
        """Extend a running maintenance window."""
        data = request.get_json()
        if not data:
            raise UnsupportedMediaType('The request does not have a json')
        maintenance = self.scheduler.get_maintenance(mw_id)
        if maintenance is None:
            raise NotFound(f'Maintenance with id {mw_id} not found')
        if 'minutes' not in data:
            raise BadRequest('Minutes of extension must be sent')
        if maintenance.status == Status.PENDING:
            raise BadRequest(
                f'Maintenance window {mw_id} has not yet started'
            )
        if maintenance.status == Status.FINISHED:
            raise BadRequest(
                f'Maintenance window {mw_id} has already finished'
            )
        try:
            maintenance_end = maintenance.end + \
                timedelta(minutes=data['minutes'])
            new_maintenance = maintenance.copy(
                update = {'end': maintenance_end}
            )
        except TypeError as exc:
            raise BadRequest('Minutes of extension must be integer') from exc

        self.scheduler.remove(maintenance.id)
        self.scheduler.add(new_maintenance)
        return jsonify({'response': f'Maintenance {mw_id} extended'}), 200
