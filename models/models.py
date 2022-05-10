import typing
from datetime import datetime

from pony.orm import Optional, Required, Set, composite_key

import utils
from models import db
from models.common import auto_renew_objects


class Model(db.Entity):
    is_checking = Required(bool, default=False)
    last_checked = Optional(datetime)
    last_modified = Required(datetime, default=datetime.now)

    def before_update(self):
        # Update time stamps
        self.last_modified = datetime.now()
        if self.is_checking:
            self.last_checked = datetime.now()

    @classmethod
    @auto_renew_objects
    def begin_checking(cls, obj):
        """
        Start the checking process (set checking-related flags in database).
        """
        obj.is_checking = True

    @classmethod
    @auto_renew_objects
    def end_checking(cls, obj, **kwargs):
        """
        Stop checking and update object's values into database using the keyword
        arguments.

        :param obj: Object
        :param kwargs: Updating values
        """
        obj.set(**kwargs)
        obj.is_checking = False

    @auto_renew_objects
    def reset_status(self):
        """
        Reset all object's status.
        """
        self.is_checking = False
        self.last_checked = None

    @auto_renew_objects
    def load_object(self):
        self.load()
        return self


class SSH(Model):
    """
    Store SSH information.
    """
    ip = Required(str)
    username = Optional(str)
    password = Optional(str)
    is_live = Required(bool, default=False)

    composite_key(ip, username, password)

    port = Optional('Port')
    used_ports: Set = Set('Port')

    def before_update(self):
        super().before_update()

        # Update used ports
        if self.port is not None and self.port not in self.used_ports:
            self.used_ports.add(self.port)

    @classmethod
    @auto_renew_objects
    def get_ssh_for_port(cls, port: 'Port', unique=True):
        """
        Get a usable SSH for provided Port. Will not get one that was used by
        that Port before if unique=True.

        :param port: Port
        :param unique: True if the SSH cannot be used before by Port
        :return: Usable SSH for Port
        """
        query = cls.select(lambda s: s.is_live)
        if unique:
            query = query.filter(lambda s: s.id not in port.used_ssh_list.id)

        if result := query.random(1):
            return result[0]
        else:
            return None


class Port(Model):
    """
    Store port information.
    """
    port_number = Required(int, unique=True, min=1024, max=65353)
    auto_connect = Required(bool, default=True)

    ssh = Optional(SSH)
    is_connected = Required(bool, default=False)
    external_ip = Optional(str)  # Proxy's external IP

    time_connected = Optional(datetime)
    used_ssh_list: Set = Set(SSH, reverse='used_ports')
    proxy_address = Optional(str)

    def before_update(self):
        super().before_update()

        # Update time connected
        if self.is_connected:
            self.time_connected = self.time_connected or datetime.now()
        else:
            self.time_connected = None

        # Update used SSH
        if self.is_connected:
            if self.ssh is not None and self.ssh not in self.used_ssh_list:
                self.used_ssh_list.add(self.ssh)

        self.proxy_address = f"socks5://{utils.get_ipv4_address()}:{self.port_number}"

    @auto_renew_objects
    def need_reset(self, time_expired: datetime):
        return self.ssh is not None and self.time_connected < time_expired

    @property
    @auto_renew_objects
    def need_ssh(self):
        return self.ssh is None

    @auto_renew_objects
    def assign_ssh(self, ssh: typing.Optional[SSH]):
        self.ssh = ssh
        self.is_connected = False

    @auto_renew_objects
    def disconnect_ssh(self, remove_from_used=False):
        if remove_from_used:
            self.used_ssh_list.remove(self.ssh)
        self.assign_ssh(None)

    @auto_renew_objects
    def reset_status(self):
        super().reset_status()
        self.external_ip = ''
        self.ssh = None
        self.is_connected = False
        self.used_ssh_list.clear()
