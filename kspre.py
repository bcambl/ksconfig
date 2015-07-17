#!/usr/bin/env python
from snack import SnackScreen, EntryWindow, ButtonChoiceWindow
from snack import Label, ListboxChoiceWindow
from time import localtime, strftime
import subprocess
import platform
import json
import re

"""
ksconfig - kspre.py
===================
Kickstart %pre script to collect hostname and initial networking information to
be handled by kspost.py.
See README.md for more information.
"""
__author__ = 'Blayne Campbell'
__copyright__ = 'Copyright 2015, Blayne Campbell'
__license__ = 'BSD'
__version__ = '1.0.1'

# Settings Begin ##############################################################

# DEBUG Flag ###
# Auto fills some fields and enables/disables some features
DEBUG = False

# Default Partition/Volume Sizes (MB)
default_boot = 500
default_root = 10000
default_tmp = 1000
default_swap = 4000
default_home = 4000
default_var = 4000
default_varlog = 4000
default_yumcache = 2000

# Allowed overhead used for calculating available disk vs required space.
disk_overhead_pct = 0.01  # 0.01 = 1%

# Disk Partitioning template ###
# Include this in kickstart file with the following syntax:
# %include /tmp/disk.part
# **Note/Warning** - You can modify this template to suit your needs
# but please be sure to modify the following:
# DiskObject.__init__
# DiskObject.write_parts
# PreConfig.get_diskconfig
# PreConfig.show_diskconfig
diskpart_tpl = """
# System bootloader configuration ( The user has to use grub by default )
bootloader --location=mbr --boot-drive={device} --append="net.ifnames=0 biosdevname=0"

# Ignore Multipath
ignoredisk --only-use={device}

# Clear the Master Boot Record
zerombr

# Clear all partition information
clearpart --all --initlabel

# Disk partitions
part /boot --fstype="xfs" --ondisk={device} --size={boot_size}
part pv.21 --fstype="lvmpv" --ondisk={device} --size={required_mb}
volgroup vg00 --pesize=4096 pv.21
logvol /  --fstype="xfs" --size={root_size} --name=lv_root --vgname=vg00
logvol /home  --fstype="xfs" --size={home_size} --name=lv_home --vgname=vg00
logvol /tmp  --fstype="xfs" --size={tmp_size} --name=lv_tmp --vgname=vg00
logvol /var  --fstype="xfs" --size={var_size} --name=lv_var --vgname=vg00
logvol /var/log  --fstype="xfs" --size={varlog_size} --name=lv_var_log --vgname=vg00
logvol /var/cache/yum  --fstype="xfs" --size={yumcache_size} --name=lv_var_cache_yum --vgname=vg00
logvol swap  --fstype="swap" --size={swap_size} --name=lv_swap --vgname=vg00

"""

# Enable/Disable IP Validation
ip_validation = True  # True/False

# Prompt for secondary network interface configuration (eth1)
second_interface = True  # True/False
# hostname 'postfix' for second NIC for adding second IP to host file
second_pfix = '-nic2'

# Server Locations (Optional) ###
# Provide a server location/domain information
locations = True  # Toggle location data
server_locations = [('Location/Domain 1',
                    ('location1.example.com',
                     'Location 1 expanded description')),
                    ('Location/Domain 2',
                     ('location2.example.com',
                      'Location 2 expanded description')),
                    ('Location/Domain 3',
                     ('location3.example.com',
                      'Location 3 expanded description')),
                    ('Custom Location/Domain', ('custom', 'custom'))]

# Settings End ################################################################

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    DEVNULL = open(os.devnull, 'wb')


def convert_size(value, in_format, out_format):
    """ Converts disk size to specified format
    :param value: interger to be converted
    :param in_format: BLK, MB, GB
    :param out_format: BLK, MB, GB
    :return: value formated to specified format
    """
    result = int()
    if in_format == "BLK":
        if out_format == "MB":
            result = int(value) >> 10
        if out_format == "GB":
            result = int(value) >> 20
    elif in_format == "MB":
        if out_format == "BLK":
            result = int(value) << 10
        if out_format == "GB":
            result = int(value) >> 10
    elif in_format == "GB":
        if out_format == "BLK":
            result = int(value) << 20
        if out_format == "MB":
            result = int(value) << 10
    return result


def disk_info():
    """ Parse output of command: sfdisk -s
    :return: Available disk/device for OS install
    """
    results = []
    disks = subprocess.Popen(['sfdisk', '-s'],
                             stdout=subprocess.PIPE).stdout.readlines()
    for line in disks:
        mapper = re.search('^/dev/mapper/.*', line)
        if mapper:
            continue
        d = re.search('/dev/(.*):$', line.split()[0])
        if d:
            dev, size = line.split()
            results.append(('%s - %.1f GB' % (d.group(1),
                                              convert_size(size, 'BLK', 'GB')),
                            (d.group(1), convert_size(size, 'BLK', 'MB'))))
    return sorted(results)


def val(ip):
    """ validate IP address
    """
    cidr = False
    octcount = False
    octets = ip.split('.')
    for n in octets:
        if '/' in n:  # ToDo: Regex for [0-9] loop or d+
            cidr = True
    valid_ip = '\\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.)' \
               '{3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\b'
    if len(octets) == 4:
        octcount = True
    is_valid = re.match(valid_ip, ip)
    if is_valid and octcount and not cidr:
        return True


def get_gateway(ip, nm):
    result = {}

    def get_ip_value(ipaddr):
        """
        Calculates the binary value of the ip addresse
        """
        ipaddr = ipaddr.split('.')
        value = 0
        for i in range(len(ipaddr)):
            value = (value | (int(ipaddr[i]) << (8 * (3-i))))
        return value

    def get_ip_notation(value):
        """
        Calculates the notation of the ip addresse given its value
        """
        notat = []
        for i in range(4):
                shift = 255 << (8 * (3-i))
                part = value & shift
                part = (part >> (8 * (3-i)))
                notat.append(str(part))
        notat = '.'.join(notat)
        return notat

    def get_net_part(ipaddr, subnet):
        ipaddr = get_ip_value(ipaddr)
        subnet = get_ip_value(subnet)
        netpart = ipaddr & subnet
        netpart = get_ip_notation(netpart)
        return netpart

    def get_cidr_subnet(cidr):
        """
        Calculates the Subnet based on the CIDR
        """
        subn = 4294967295 << (32 - int(cidr))  # 4294967295 = all bits set to 1
        subn = (subn % 4294967296)  # round it back to be 4 bytes
        subn = get_ip_notation(subn)
        return subn
    try:
        if len(nm) <= 2 and int(nm) in range(0, 33):
            nm = get_cidr_subnet(nm)
            result['subnet'] = nm
            defaultgw = get_net_part(ip, nm)
        else:
            defaultgw = get_net_part(ip, nm)
            result['subnet'] = nm
        defaultgw = get_ip_value(defaultgw) + 1
        defaultgw = get_ip_notation(defaultgw)
        result['gateway'] = defaultgw
    except ValueError:
        result = {'subnet': nm, 'gateway': ''}
    return result


def dmidec(keyword):
    d = subprocess.Popen(['dmidecode', '-s', '%s' % keyword],
                         stdout=subprocess.PIPE).stdout.readlines()
    return d[0].strip('\n')


def get_interfaces():
    """ Return interface(s) by querying /proc/net/dev and /sys/class/net
    :return: dict = {'interface': {'perm_address': '00:00:00:00:00:00'}
    """
    procnetdev = subprocess.Popen(['cat', '/proc/net/dev'],
                                  stdout=subprocess.PIPE).stdout.readlines()
    interface_list = []
    valid_interfaces = {}
    for i in procnetdev:
        iface = re.match(r'^(.*):.*$', i)
        if iface:
            interface_found = iface.group(1).strip()
            if interface_found != 'lo':
                interface_list.append(interface_found)
    for interface in interface_list:
        class_path = '/sys/class/net/%s/address' % interface
        if os.path.exists(class_path):
            mac_addr = subprocess.Popen(('cat', class_path),
                                        stdout=subprocess.PIPE, stderr=DEVNULL)
            mac_addr = mac_addr.communicate()[0]
            valid_interfaces[interface] = {'perm_address': mac_addr.strip()}
        else:
            valid_interfaces[interface] = {'perm_address': ''}
    return valid_interfaces


def os_version():
    release = subprocess.Popen(['uname', '-a'], stdout=subprocess.PIPE)
    release = release.stdout.readlines()
    release = str(release).split()[2]
    release = release.split('.')[3]
    return release


class ServerObject:
    """ Server Object
    """

    def __init__(self):
        self.builddate = strftime("%a %d %b %Y %H:%M:%S", localtime())
        self.hostname = ''  # Hostname
        self.interfaces = get_interfaces()
        self.pripaddr = ''  # Primary IP Address
        self.pripmask = ''  # Primary IP Netmask
        self.pripgate = ''  # Primary IP Gateway
        self.primedns = ''  # Primary DNS
        self.secondns = ''  # Secondary DNS
        if second_interface:
            self.secondipaddr = ''  # Second Interface IP Address
            self.secondipmask = ''  # Second Interface IP Netmask
            self.secondipgate = ''  # Second Interface IP Gateway
            self.second_pfix = second_pfix  # Second Interface hostname postfix
        self.osversion = os_version()
        self.serverarch = platform.processor()
        self.servertype = dmidec('system-product-name')
        self.domain = ''
        self.location = ''
        if DEBUG:
            # Debug/Test Section
            self.hostname = 'testhost'
            self.pripaddr = '192.168.122.50'
            self.pripmask = '255.255.255.0'
            self.pripgate = '192.168.122.1'
            self.primedns = '8.8.8.8'
            self.secondns = '8.8.4.4'
            if second_interface:
                self.secondipaddr = '192.168.122.150'
                self.secondipmask = '255.255.255.0'
                self.secondipgate = '192.168.122.1'

    def validate_ip(self):
        self.invalids = []  # Empty the invalid IP list
        for i, v in vars(self).iteritems():
            if i in ('hostname', 'invalids', 'location', 'builddate', 'domain',
                     'serverarch', 'servertype', 'osversion', 'second_pfix'):
                continue  # Skip validation for non-ip keys
            if val(v):
                continue  # IPv4 validation tests passed
            else:
                self.invalids.append(v)
        if self.invalids:
            self.invalids = filter(None, self.invalids)
            if not self.invalids:
                self.invalids.append("Blank IP Address Field(s) Detected")
            return self.invalids

    def write_servercfg(self):
        """ Write servercfg.json file
        """
        with open('/tmp/servercfg.json', 'w') as f:
            f.write(json.dumps(vars(self), sort_keys=True, indent=4))


class DiskObject:
    """ Disk partition object
    """

    def __init__(self):
        self.device = ''
        self.avail_mb = 0
        self.required_mb = 0
        self.diskdiff = 0
        # Define Default Partitions from settings section (MB):
        self.boot = default_boot
        self.root = default_root
        self.tmp = default_tmp
        self.swap = default_swap
        self.home = default_home
        self.var = default_var
        self.varlog = default_varlog
        self.yumcache = default_yumcache

    def validate_parts(self):
        self.required_mb = 0
        for i in vars(self).items():
            if i[0] in ('device', 'avail_mb', 'required_mb', 'diskdiff'):
                continue  # Exclude from validation
            else:
                self.required_mb += int(i[1])
        self.required_mb += int(self.required_mb * disk_overhead_pct)
        if self.required_mb < self.avail_mb:
            self.diskdiff = int(self.avail_mb) - int(self.required_mb)
            return False
        else:
            # ToDo: Add user feedback
            self.diskdiff = int(self.avail_mb) - int(self.required_mb)
            return True

    def write_parts(self):
        """ Writes disk configuration files.
        See Settings -> diskpart_tpl for disk.part template
        :return: /tmp/disk.part & /tmp/disk.json
        """
        context = {
            "device": self.device,
            "required_mb": self.required_mb,
            "boot_size": self.boot,
            "yumcache_size": self.yumcache,
            "home_size": self.home,
            "swap_size": self.swap,
            "var_size": self.var,
            "varlog_size": self.varlog,
            "root_size": self.root,
            "tmp_size": self.tmp,
        }
        # Write /tmp/disk.part to be included in kickstart
        with open('/tmp/disk.part', 'w') as f:
            f.write(diskpart_tpl.format(**context))
        # Serialize data in JSON format for future use
        with open('/tmp/disk.json', 'w') as f:
            f.write(json.dumps(vars(self), sort_keys=True, indent=4))


class BlankLabel(Label):
    """ Create a blank label by inheriting a snack.Label with a blank value
    """
    def value(self):
        pass


class PreConfig:
    """ Collect information about server
    :returns:
    (u'ok', ('hostname', None, 'priip', 'prisub', 'defgw', 'pridns', 'snddns',
    None, 'bkip', 'bksub'))
    """

    def __init__(self):
        self.screen = SnackScreen()
        self.screen.drawRootText(1, 0,
                                 "Kickstart Server Pre-Configuration")
        self.screen.drawRootText(1, 1, "v. " + __version__)
        self.screen.refresh()
        self.complete = 0

    def get_location(self, svrobj):
        """ Prompt for server location specified by settings
        """
        location = ListboxChoiceWindow(self.screen, 'Server Location',
                                       'Select a location/domain:',
                                       server_locations, buttons=['Ok'],
                                       help=None)
        if location[0] != 'cancel':
            if location[1][0] == 'custom':
                custom_loc = EntryWindow(self.screen, 'Custom Location/Domain',
                                         '', ['Domain', 'Description'],
                                         buttons=['ok'], help=None)
                svrobj.domain = custom_loc[1][0]
                svrobj.location = custom_loc[1][1]
            else:
                svrobj.domain = location[1][0]
                svrobj.location = location[1][1]

    def get_network(self, svrobj):
        """ Prompt for Hostname and network IP's
        """
        network_fields = [("Hostname", "%s" % svrobj.hostname),
                          ('', BlankLabel('')),
                          ("IP Address", "%s" % svrobj.pripaddr),
                          ("Subnet/CIDR", "%s" % svrobj.pripmask),
                          ("Default Gateway", "%s" % svrobj.pripgate),
                          ("Primary DNS", "%s" % svrobj.primedns),
                          ("Secondary DNS", "%s" % svrobj.secondns)]
        if second_interface:
            network_fields.append(('', BlankLabel('')))
            network_fields.append(("2nd Interface IP", "%s" %
                                   svrobj.secondipaddr))
            network_fields.append(("2nd Interface Subnet/CIDR", "%s" %
                                   svrobj.secondipmask))
            network_fields.append(("2nd Interface Gateway", "%s" %
                                   svrobj.secondipgate))
        info = EntryWindow(self.screen, "Server Information",
                           '', network_fields, help=None)

        if info[0] != 'cancel':
            svrobj.hostname = info[1][0]
            svrobj.pripaddr = info[1][2]
            svrobj.pripmask = info[1][3]
            svrobj.pripgate = info[1][4]
            svrobj.primedns = info[1][5]
            svrobj.secondns = info[1][6]
            if second_interface:
                svrobj.secondipaddr = info[1][8]
                svrobj.secondipmask = info[1][9]
                svrobj.secondipgate = info[1][10]
                if not svrobj.secondipgate or len(svrobj.secondipmask) == 2:
                    find_gw = get_gateway(info[1][8], info[1][9])
                    svrobj.secondipmask = find_gw['subnet']
                    svrobj.secondipgate = find_gw['gateway']
        if not svrobj.pripgate or len(svrobj.pripmask) == 2:
            find_gw = get_gateway(info[1][2], info[1][3])
            svrobj.pripmask = find_gw['subnet']
            svrobj.pripgate = find_gw['gateway']

    def show_invalid(self, svrobj):
        """ Display IPv4 addresses that did not pass validations
        """
        if svrobj.invalids:
            invalid_addr = ''
            for ip in svrobj.invalids:
                if "Blank IP Address Field(s) Detected" in ip:
                    invalid_addr += "%s " % ip
                elif '/' in ip:
                    invalid_addr += '%s (remove cidr notation)\n' % ip
                else:
                    invalid_addr += '%s (invalid IP address)\n' % ip
            prompt = ButtonChoiceWindow(self.screen, "Invalid IP's Detected",
                                        invalid_addr,
                                        buttons=['edit', 'skip ip validation'],
                                        help=None)
            if prompt == 'skip ip validation':
                global ip_validation
                ip_validation = False
        else:
            pass

    def show_serverinfo(self, svrobj):
        """ Displays hostname and network IP configuration before confirmation.
        """
        serverinfo_tpl = """
Hostname ---------------> {hostname}
IP Address -------------> {pripaddr}
Subnet -----------------> {pripmask}
Default Gateway --------> {pripgate}
Primary DNS ------------> {primedns}
Secondary DNS-----------> {secondns}
"""
        if second_interface and svrobj.secondipaddr != '':
            serverinfo_tpl += """
2nd Interface IP -------> {secondipaddr}
2nd Interface Subnet ---> {secondipmask}
2nd Interface Gateway --> {secondipgate}
"""
        context = {
            "hostname": svrobj.hostname,
            "pripaddr": svrobj.pripaddr,
            "pripmask": svrobj.pripmask,
            "pripgate": svrobj.pripgate,
            "primedns": svrobj.primedns,
            "secondns": svrobj.secondns,
        }
        if second_interface:
            context["secondipaddr"] = svrobj.secondipaddr
            context["secondipmask"] = svrobj.secondipmask
            context["secondipgate"] = svrobj.secondipgate
        ButtonChoiceWindow(self.screen, "Verify Hostname & IP's",
                           serverinfo_tpl.format(**context), help=None)

    def get_diskinfo(self, dskobj):
        """ Select disk to be used as for operating system installation.
        :param dskobj: DiskObject
        :return: Nothing
        """
        avail_disks = ListboxChoiceWindow(self.screen, 'Available Disks',
                                          'Select disk for OS install:',
                                          disk_info(), help=None)
        dskobj.device = avail_disks[1][0]
        dskobj.avail_mb = avail_disks[1][1]

    def get_diskconfig(self, dskobj):
        """ Prompt user to modify volume sizes or accept defaults specified by
        settings
        :param dskobj: DiskObject
        :return: Nothing
        """
        dskobj.validate_parts()  # Run validator to populate required space
        disk_config = EntryWindow(self.screen, 'Configure Disk',
                                  'Available space = %s MB\n'
                                  'Required space = %s MB' %
                                  (dskobj.avail_mb, dskobj.required_mb),
                                  [('/boot', '%s' % dskobj.boot),
                                   ('/', '%s' % dskobj.root),
                                   ('/tmp', '%s' % dskobj.tmp),
                                   ('/home', '%s' % dskobj.home),
                                   ('/var', '%s' % dskobj.var),
                                   ('/var/log', '%s' % dskobj.varlog),
                                   ('/var/cache/yum', '%s' % dskobj.yumcache),
                                   ('swap', '%s' % dskobj.swap)],
                                  buttons=['update', 'reset'])

        if disk_config[0] != 'reset':
            # ToDo: Regex validations for user input
            dskobj.boot = disk_config[1][0]
            dskobj.root = disk_config[1][1]
            dskobj.tmp = disk_config[1][2]
            dskobj.home = disk_config[1][3]
            dskobj.var = disk_config[1][4]
            dskobj.varlog = disk_config[1][5]
            dskobj.yumcache = disk_config[1][6]
            dskobj.swap = disk_config[1][7]

        else:
            dskobj.boot = default_boot
            dskobj.root = default_root
            dskobj.tmp = default_tmp
            dskobj.home = default_home
            dskobj.var = default_var
            dskobj.varlog = default_varlog
            dskobj.yumcache = default_yumcache
            dskobj.swap = default_swap

    def show_diskconfig(self, dskobj):
        """ Displays disk volume configuration before confirmation.
        """
        diskconfig_tpl = """
    /boot -----------> {boot}
    / ---------------> {root}
    /tmp ------------> {tmp}
    /home -----------> {home}
    /var ------------> {var}
    /var/log --------> {varlog}
    /var/cache/yum --> {yumcache}

    swap ------------> {swap}
"""
        context = {
            "boot": dskobj.boot,
            "root": dskobj.root,
            "tmp": dskobj.tmp,
            "home": dskobj.home,
            "var": dskobj.var,
            "varlog": dskobj.varlog,
            "yumcache": dskobj.yumcache,
            "swap": dskobj.swap,
        }
        ButtonChoiceWindow(self.screen, "Verify Disk Configuration",
                           diskconfig_tpl.format(**context), help=None)

    def check_complete(self):
        """ Prompt user to accept configuration or review/edit configuration.
        :return:
        """
        complete = ButtonChoiceWindow(self.screen, 'Confirm Configuration', '',
                                      buttons=['Accept', 'Re-configure'])
        if complete == 'accept':
            self.complete = 1
        else:
            # Re-enable IP validation
            global ip_validation
            ip_validation = True

    def exit(self):
        """ clean-up on exit
        """
        self.screen.finish()


def main(config, server, disk):
    while config.complete == 0:
        if locations:
            config.get_location(server)
        config.get_network(server)
        while server.validate_ip() and ip_validation:
            config.show_invalid(server)
            if ip_validation:
                config.get_network(server)
        config.get_diskinfo(disk)
        config.get_diskconfig(disk)
        disk.validate_parts()
        while disk.diskdiff < 0:
            config.get_diskconfig(disk)
            disk.validate_parts()
        config.show_serverinfo(server)
        config.show_diskconfig(disk)
        config.check_complete()
    # Pass second_interface value to post script
    server.second_interface = second_interface
    # Write Configurations
    server.write_servercfg()
    disk.write_parts()


if __name__ == "__main__":
    pre_config = PreConfig()
    server_config = ServerObject()
    disk_config = DiskObject()
    main(pre_config, server_config, disk_config)

    pre_config.exit()
