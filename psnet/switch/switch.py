import os
import sys
import time
import logging
import simplejson
from os import path,getenv

from ..ui import dialogs
from ..survey import survey
from ..netconfig import netconfig

module_logger = logging.getLogger(__name__)

switch_types = {
    'arista'     : survey.AristaSurveyer,
    'brocade'    : survey.BrocadeSurveyer,
    'ruckus'     : survey.RuckusSurveyer,
    'cisco'      : survey.CiscoSurveyer,
}

CONFIG_DIR = path.join(getenv("RELDIR"), 'config')


def determine_type(nc, name):
    """
    Return the type of the switch based on the list of switches kept in the
    CONFIG_DIR directory

    :param nc: The netconfig information.
    :type  name: netconfig.NetConfig

    :param name: The name of the switch
    :type  name: str

    :return: The type of switch based on the netconfig description.
    """
    try:
        n = nc.find_hosts(name, as_dict=True)[name]
        d = n['description'].lower()
        for s in switch_types.keys():
            if s in d:
                module_logger.info("%s is a%s %s switch." % (name, "n" if s[0] in 'aeiou' else "", s))
                return s
    except:
        d = ""
    raise RuntimeError(
        f"Switch {name} is either an unsupported type or does not have "
        "the switch type in its netconfig description. "
        f'The description was "{d}", and the '
        f"supported switch types are {', '.join(switch_types.keys())}. "
    )

"""
What do we have in here?
    _vlan: list of Vlan objects.
    _portmap: map from port name to vlan number.
    _power: map from port name to PoE state.
    _labels: map from port name to port name.
"""
class Switch(netconfig.host.Host):
    """
    A class to represent a network Switch.

    :param switch_name: The name of the switch in NetConfig
    :type  switch_name: str
    
    :param user: The username used to log into the switch, by default this is
                 the administrator username 
    :type  user: str

    :param pw: The password of the switch, if this is not specified the
              password will be requested in the terminal 
    :type  pw: str

    :param enablepw: The enable password of the switch, if this is not specified, the
              password will be requested in the terminal, if needed.
    :type  enablepw: str

    :param type: The type of the switch; arista, brocade or cisco. If this not
                selected the database of switches will queried using the
                determine_type function.
    :type  type: str
    """
    timeout = 5
    _port    = 22
    _vlan_alias = 'VLAN_{:}'
    _vlan    = []
    _user    = 'admin'

    def __init__(self,switch_name,user='admin',pw=None,enablepw=None,type=None):
        self._nc   = netconfig.NetConfig()

        if not type:
            type = determine_type(self._nc, switch_name)
            module_logger.info('No switch type supplied guessing '\
                               'that switch is type {:}'.format(type))

        self.type = type
        host_info = list(self._nc.find_hosts(switch_name,as_dict=True).values())[0]
        super(Switch,self).__init__(switch_name,host_info)

        #Check host 
        ping = self.ping()
        if not ping:
            raise IOError('Unable to ping {:}'.format(switch_name))
        #Request password if not supplied
        if user:
            self._user = user

        if not pw:
            self._pw = dialogs.passwddialog.getPassword('Password for {:}: '.format(self._user))
        else:
            self._pw = pw
        self._enablepw = enablepw

    @property
    def subnets(self):
        """
        The list of vlan number,subnet pairs that are found on the switch
        """
        subnets = [(vlan._vlan_no,vlan.subnet) for vlan in self._vlan]
        return sorted(subnets,key = lambda sub: int(sub[0]))

    # This is either "EtXX" or "X/Y/Z".  Convert this to an int in order in either case.
    def _portKey(self, k):
        if k[:2] == 'Et':
            return int(k[2:])
        l = [int(x) for x in k.split("/")]
        s = 0
        for x in l:
            s = 1000 * s + x
        return s

    @property
    def ports(self):
        """
        Return all of the ports on the switch
        """
        ports = []
        for vlan in self._vlan:
            ports.extend(vlan.ports)
        return sorted(ports, key=self._portKey)

    def power(self):
        """
        Return the power information for the switch.
        """
        return self._power

    def get_enablepw(self):
        module_logger.info('Prompting for enable password')
        self._enablepw = dialogs.passwddialog.getPassword('Enable password for {:}: '.format(self._user))

    def set_power(self, port, state):
        # This is a privileged command: do we need/have the enable password?
        if not self._enablepw and self._surveyer().check_mode(self.name):
            self.get_enablepw()
        commands = ['config terminal',
                    'interface ethernet %s' % port,
                    '%sinline power' % ("no " if state==0 else ""),
                    'exit', 
                    'exit']
        #Run commands
        module_logger.info('Turning %s power for %s' % ("off" if state==0 else "on", port))
        cmd = self._surveyer()._cmd_runner(self._user,
                                           self._pw,
                                           self._enablepw,
                                           self._port,
                                           commands,
                                           timeout=self.timeout,
                                           priv=True)
        try:
            out_code,resp = cmd.run(self.name)
        except IOError:
            module_logger.info("Bad enable password!")
            self._enablepw = None
            
        module_logger.info('Finished running switch commands')
        self.update_port(port, 15 if state==0 else 20)

    def labels(self):
        """
        Return the power information for the switch.
        """
        return self._labels

    def set_name(self, port, name):
        # This is a privileged command: do we need/have the enable password?
        if not self._enablepw and self._surveyer().check_mode(self.name):
            self.get_enablepw()
        
        commands = ['config terminal', 
                    'interface ethernet %s' % port]
        if name == "":
            commands.extend(['no port-name',
                             'exit',
                             'exit'])
        else:
            commands.extend(['port-name %s' % name,
                             'exit',
                             'exit'])
        #Run commands
        module_logger.info('Setting port-name for %s to "%s"' % (port, name))
        cmd = self._surveyer()._cmd_runner(self._user,
                                           self._pw,
                                           self._enablepw,
                                           self._port,
                                           commands,
                                           timeout=self.timeout,
                                           priv=True)
        try:
            out_code,resp = cmd.run(self.name)
        except IOError:
            module_logger.info("Bad enable password!")
            self._enablepw = None
        module_logger.info('Finished running switch commands')
        self.update_port(port)

    def find_vlans(self, plist):
        return [self._portmap[p] for p in plist]

    @property
    def devices(self):
        """
        Return a dictionary of all of the devices on the switch.

        Each device has a sub-dictionary that returns the VLAN number,
        mac-address and port of the device
        """
        devices = {}
        for vlan in self._vlan:
            devices.update(vlan._devices)
        
        return devices
   

    @property
    def unknown_devices(self):
        """
        Return a dictionary of all of the devices on the switch who are not
        associated with an entry in NetConfig

        Each device has a sub-dictionary that returns the VLAN number,
        mac-address and port of the device
        """
        devices = {}
        for vlan in self._vlan:
            devices.update(vlan._unknown)
        
        return devices
    

    def load_ports(self):
        """
        Load the ports found on each VLAN
        """
        self._vlan = []
        #Load vlan information
        module_logger.info('Loading port locations from switch')
        vlan = self._surveyer().show_vlan(self.name)
        
        #Organize
        self._portmap = {}
        for vlan_no,ports in vlan.items():
            module_logger.debug('Found VLAN {:} on switch'.format(vlan_no))
            v = Vlan(vlan_no,ports,switch=self)
            self._vlan.append(v)
            setattr(self,self._vlan_alias.format(str(vlan_no)),v)
            for p in ports:
                self._portmap[p] = vlan_no

    def find_connections(self):
        """
        Load the devices connected to the switch
        """
        for vlan in self._vlan:
            vlan._devices = {}
            vlan._unknown = {}

        module_logger.info('Requesting mac addresses from switch')
        mac = self._surveyer().show_mac(self.name)
        module_logger.info('Searching for mac addresses in NetConfig')
        for port,address in mac.items():
            module_logger.debug('Found {:} on port {:}.'.format(port,address))
            vlan_no = self.find_port(port)
            if not vlan_no:
                module_logger.debug('{:} is a tagged port, '\
                                   'ignoring mac address'.format(port))
                pass
            else:
                #Find VLAN
                vlan_name = self._vlan_alias.format(vlan_no)
                vlan = getattr(self,vlan_name)
                try:
                    node = self._nc._mac[address.lower()]
                    vlan._devices[node] = {'ethernet_address':address,
                                           'port':port,
                                           'vlan':vlan_no}
                except KeyError:
                    module_logger.debug('Unable to find NetConfig entry for '\
                                        '{:} on port {:}'.format(address,port))
                    vlan._unknown[address] = {'port':port,'vlan':vlan_no}
        module_logger.info('Mac address processing complete')
                    

    def update(self):
        """
        Load both the current port locations as well as the connected devices.
        """
        self.load_ports()
        self.find_connections()
        self.load_power()
        self.load_labels()
        module_logger.info('Switch information updated')

    def update_port(self, port, delay=0.5):
        """
        Update the power, port-name, and mac address information for the specified port.
        
        We'll assume the VLAN hasn't changed... that needs a full layout.
        """
        module_logger.info('Delaying %g seconds for switch to settle.' % delay)
        time.sleep(delay)
        module_logger.info('Updating switch information for port %s' % port)
        (pwr, name, address) = self._surveyer().update_port(self.name, port)
        self._power[port] = pwr
        self._labels[port] = name
        vlan_no = self.find_port(port)
        if vlan_no:
            vlan_name = self._vlan_alias.format(vlan_no)
            vlan = getattr(self,vlan_name)
            dname = ""
            if address == "":
                found = False
                for node, d in vlan._devices.items():
                    if d['port'] == port:
                        del vlan._devices[node]
                        found = True
                        break
                if not found:
                    for a, d in vlan._unknown.items():
                        if d['port'] == port:
                            del vlan._unknown[a]
                            break
            else:
                try:
                    node = self._nc._mac[address.lower()]
                    dname = node
                    vlan._devices[node] = {'ethernet_address':address,
                                           'port':port,
                                           'vlan':vlan_no}
                except KeyError:
                    module_logger.debug('Unable to find NetConfig entry for '\
                                        '{:} on port {:}'.format(address,port))
                    vlan._unknown[address] = {'port':port,'vlan':vlan_no}
            self.update_port_gui(port, vlan_no, address, name, dname, pwr)
        module_logger.info('Switch information updated')

    def update_port_gui(self, port, vlan, mac, name, dname, pwr):
        pass

    def load_power(self):
        module_logger.info('Loading Power over Ethernet information')
        self._power = self._surveyer().show_power(self.name)

    def load_labels(self):
        module_logger.info('Loading port-name information')
        self._labels = self._surveyer().show_labels(self.name)
    
    def find_port(self,port):
        """
        Find VLAN number for a port

        :param port: The port name
        :type port: str

        :return: The VLAN number the port is found on. If the port is not found
                 None is returned
        :rtype: str
        """
        try:
            num = self._portmap[port]
            module_logger.debug('Found {:} on VLAN {:}'.format(port,num))
            return num
        except:
            module_logger.debug('Unable to find port {:} on any VLAN'.format(port))
            return None
    
    def find_device(self,device):
        """
        Find a device on the switch by its NetConfig name

        :param device: The name of the device
        :type  device: str

        :return: A tuple of the VLAN the device is on, as well as the port. If
                 the device is not found, two NoneTypes are returned
        :rtype: str
        """
        for vlan in self._vlan:
            if device in vlan.devices:
                num = vlan._vlan_no
                port = vlan._devices[device]['port']
                module_logger.debug('Found {:} on VLAN {:} port '\
                                    '{:}'.format(device,num,port))
                return num,port

        module_logger.debug('Unable to find device {:} on any VLAN'.format(device))
        return None,None

    def find_device_substr(self,device):
        """
        Find a device on the switch by its NetConfig name

        :param device: A substring of the name of the device
        :type  device: str

        :return: A list of (device, vlan, port) tuples.  If an exact
                 match is found, only this is returned, but if no exact
                 matches are found, all matches are returned.  (An empty
                 list is returned if there are no matches.)
        :rtype: list
        """
        l = []
        dl = len(device)
        for vlan in self._vlan:
            for d in vlan.devices:
                if device in d:
                    num = vlan._vlan_no
                    port = vlan._devices[d]['port']
                    module_logger.debug('Found {:} on VLAN {:} port '\
                                        '{:}'.format(d,num,port))
                    if device == d: # If it's an exact match, just return it!
                        return [(d,num,port)]
                    else:
                        l.append((d,num,port))
        if l == []:
            module_logger.debug('Unable to find device {:} on any VLAN'.format(device))
        return sorted(l, key=lambda sub: sub[0])
   

    def find_vlan_for_subnet(self,subnet):
        """
        Return the correct VLAN number for a specific subnet
        
        :param subnet: Name of the subnet
        :type  subnet: str

        :return: The number of the associated VLAN. If not found, None is
                 returned
        :rtype: str
        """
        for (vlan,vlan_subnet) in self.subnets:
            if subnet == vlan_subnet:
                return vlan
        module_logger.debug('No VLAN associated with subnet {:}'.format(subnet))
        return None


    def find_subnet_for_host(self,host):
        """
        Return the correct vlan and subnet name for a given host

        :param host: The name of a host
        :type  host: str

        :return: The vlan number and subnet associated with the devices
                 NetConfig entry
        :rtype: tuple
        """
        host = self._load_host(host)
        vlan = self.find_vlan_for_subnet(host.subnet)

        return vlan,host.subnet
   

    def move_port(self,port,vlan_no,verify=True):
        """
        Move a port to a specified VLAN
    
        The return of the function will be whether or not the move was
        executed. If verify is set to True, this means that port information is
        reloaded and then checked, otherwise this simply indicates that the
        command was given to the switch.
        
        :param port: The name of the port to be moved
        :type  port: str

        :param vlan_no: The VLAN number that is destination for the port
        :type  vlan_no: str

        :param verify: The user has the choice to reload the Switch information
                       after move is completed. This should usually be done,
                       but if a number of moves are going to be completed in
                       succession this can take an unneccesary amount of time.
                       In this case, verify can be set to false, but the class
                       function update should be called after all the moves
                       are done 
        :type verify:  bool

        :rtype: bool
        """
        # This is a privileged command: do we need/have the enable password?
        if not self._enablepw and self._surveyer().check_mode(self.name):
            self.get_enablepw()
        
        commands = ['config terminal']
        vlan_no  = str(vlan_no)

        #Find origin of port
        origin = self.find_port(port) 
        
        #Check if valid port
        if not origin:
            module_logger.error('Port {:} is not this switch'.format(port))
            return False
        
        #Check if already at destination
        if origin == vlan_no:
            module_logger.info('Port is already on VLAN {:}'.format(origin))
            return True

        #Not neccesary to move if on default
        if not origin == '1':
            commands.extend(['vlan {:}'.format(origin),
                             'no untag ethernet {:}'.format(port),
                             'exit'])
        else:
            module_logger.debug('{:} is already on default '\
                                'VLAN'.format(port))
        
        #Check if destination vlan is valid
        if not vlan_no == '1':
            if vlan_no in [vlan._vlan_no for vlan in self._vlan]:
                commands.extend(['vlan {:}'.format(vlan_no),
                                    'untag ethernet {:}'.format(port),
                             'exit',
                             'exit'])
            else:
                module_logger.error('VLAN {:} is not on this switch'.format(vlan_no))
                return False
        
        else:
            commands.extend(['exit'])

        #Run commands
        cmd = self._surveyer()._cmd_runner(self._user,
                                           self._pw,
                                           self._enablepw,
                                           self._port,
                                           commands,
                                           timeout=self.timeout,
                                           priv=True)
        
        try:
            out_code,resp = cmd.run(self.name)
        except IOError:
            module_logger.info("Bad enable password!")
            self._enablepw = None
        module_logger.info('Finished running switch commands')

        if not verify:
            return True
        
        self.update()
        final = self.find_port(port)
        if final == vlan_no:
            module_logger.info('Port {:} is now on '\
                               'VLAN {:}'.format(port,vlan_no))
            return True
        else:
            module_logger.warning('Port move was unsuccesful, '\
                                  'port {:} is now on VLAN {:}'.format(port,final))
        

    def move_device(self,device,subnet=None,vlan_no=None,
                    verify=True):
        """
        Move a device on to either a specific subnet or VLAN The return of the
        function will be whether or not the move was executed. If verify is set
        to True, this means that port information is reloaded and then checked,
        otherwise this simply indicates that the command was given to the
        switch.
       
        :param device: The name of the device to be moved
        :type  device: str

        :param subnet: The name of the subnet can be entered and the
                       corresponding VLAN will be found. You can view the names
                       of the subnets found on the switch using the class
                       attribute subnets
        :type  subnet: str

        :param vlan_no: If you want to instead specify the destination of the
                        device, you can enter the vlan number as a keyword
        :type  vlan_no: str

        :param verify: The user has the choice to reload the Switch information
                       after move is completed. This should usually be done,
                       but if a number of moves are going to be completed in
                       succession this can take an unneccesary amount of time.
                       In this case, verify can be se to false, but the class
                       function 'update' should be called after all the moves
                       are done 
        :type verify:  bool

        :rtype: bool
        """
        if not any([subnet,vlan_no]):
            module_logger.error('Please select either a target subnet or VLAN')
            return False

        vlan,port = self.find_device(device)

        if not all([vlan,port]):
            module_logger.error('No device named {:} on switch'.format(device))
            return False
        
        if subnet:
            vlan_no = self.find_vlan_for_subnet(subnet)
            if not vlan_no:
                module_logger.error('{:} was not found on this switch'.format(subnet))
                return False
        
        module_logger.info('Moving {:} on port {:} to VLAN {:}'.format(device,port,vlan_no))

        ret = self.move_port(port,vlan_no,verify=verify)

        return ret


    def survey(self):
        """
        Find all devices on the wrong subnet

        This function looks at all of the devices found on the switch and
        determines whether the device is on the correct subnet by comparing the
        name of the subnet associated with the VLAN to the information in
        NetConfig

        :return: A list of devices on the wrong subnet
        :rtype: list
        """
        misplaced = []
        [misplaced.extend(vlan.survey()) for vlan in self._vlan]
        return misplaced

    
       

    def auto_configure(self):
        """
        Find all devices that are on the incorrect subnets and move them to the
        correct one

        This will automatically move ports on the switch, so use with care. It
        is also recommended that you are watching the log statements coming
        from the module to make sure that you know which ports are moved
        """
        misplaced = self.survey()
        for device in misplaced:
            module_logger.info("Attempting to move {:}".format(device))
            vlan,subnet = self.find_subnet_for_host(device)
            if vlan:
                verify = self.move_device(device,subnet=subnet,
                                          update=False,verify=False)
                if not verify:
                    module_logger.warn('Unable to move device {:} on to '\
                                       'subnet {:}'.format(device,host['subnet']))
            else:
                module_logger.warn('Device {:} can not be moved to the subnet '\
                                   '{:} because it is not present on the '\
                                   'switch'.format(device,subnet))
        
        self.update()
        unmoveable = self.survey()
        for device in unmoveable:
            module_logger.warn('{:} remains on the wrong '\
                               'subnet'.format(unmoveable))

    def write_memory(self):
        """
        Save the current config to the switch so that it persists after next reboot.
        """
        # This is a privileged command: do we need/have the enable password?
        if not self._enablepw and self._surveyer().check_mode(self.name):
            self.get_enablepw()

        commands = ['write memory']
        cmd = self._surveyer()._cmd_runner(self._user,
                                           self._pw,
                                           self._enablepw,
                                           self._port,
                                           commands,
                                           timeout=self.timeout,
                                           priv=True)
        try:
            out_code,resp = cmd.run(self.name)
        except IOError:
            module_logger.info("Bad enable password!")
            self._enablepw = None
            out_code = 1
            resp="Bad enable password"
        except Exception:
            out_code = 1
            resp=""
        if out_code:
            module_logger.error(f"Write memory had an error: {resp}")
        else:
            module_logger.info("Write memory complete, settings saved")

    def get_configuration(self):
        """
        Package the VLAN configuration information into a single dictionary
        
        :rtype: dict
        """
        cfg = {}
        for v in self._vlan:    
            v_cfg = {v._vlan_no:{'ports':v.ports,
                                 'devices':v.devices}}
            cfg.update(v_cfg)
        return cfg


    def save_configuration(self,file=None,dir=None):
        """
        Save the configuration of the switch to a JSON file

        :param file: The name of the configuration file. By default, this will
                     be a hash of the switch name and the current date and time, but can be
                     changed if a more meaningful name is desired.
        :type  file: str

        :param dir: The directory path to save the file in. By default, this
                    will be the directory specified by CONFIG_DIR/configs
        :type  dir: str
        """
        cfg = {}
        if not dir:
            dir = path.join(CONFIG_DIR,'configs')

        if not file:
            file = '{:}_{:}.json'.format(self.name,
                                         time.ctime().replace(' ','-'))
        
        module_logger.info('Saving configuration '\
                           'to {:}'.format(path.join(dir,file)))
        
        with open(path.join(dir,file),'w+') as f:
            simplejson.dump(self.get_configuration(),f)


    def diff_configuration(self,file,dir=None):
        """
        Determine the differences between a saved configuration and the current
        one

        :param file: The name of file that contains the saved configuration
        :type  file: str

        :param dir: The directory path that the saved file is contained in. By
                    default, the configuration is looked for in CONFIG_DIR/configs
        :type  dir: str

        :return: A dictionary of the differences between the saved
                 configuration and the current one. There is one sub-dictionary
                 that contains all of the devices that have moved, with current
                 and past sub-dictionaries, and one that contains the same but
                 for each port that has moved
        """
        current_cfg = self.get_configuration()
        moved       = {'devices':{},'ports':{}}
        if not dir:
            dir = path.join(CONFIG_DIR,'configs')
        
        file = path.join(dir,file)
        
        module_logger.info('Comparing current configuration to the saved file '\
                           '{:}'.format(file))
        
        if not path.exists(path.join(file)):
            raise IOError('{:} is not a valid filename'.format(file))
        
        with open(file,'r') as cfg:
            past_config = simplejson.load(cfg)


        for vlan,info  in past_config.items():
            current = current_cfg.get(vlan)
            if not current:
                module_logger.warning('VLAN {:} is not on switch '\
                                      'anymore'.format(vlan))
            else:
                for port in info['ports']:
                    if port not in current['ports']:
                        current_vlan = self.find_port(port)
                        module_logger.info('Port {:} has moved '
                                           'from {:} to {:}'.format(port,
                                                                    vlan,
                                                                    current_vlan))
                        moved['ports'][port] = {'past':vlan,'current':current_vlan}

                for device in info['devices']:
                    if device not in current['devices']:
                        current_vlan,port  = self.find_device(device)
                        if current_vlan:
                            module_logger.info('Device {:} has moved '
                                               'from {:} to {:}'.format(device,
                                                                        vlan,
                                                                        current_vlan))
                            moved['devices'][device] = {'past':vlan,'current':current_vlan}
                        else:
                            module_logger.warning('Device {:} is no longer '\
                                                  'on the switch'.format(device))
                            moved['devices'][device] = {'past':vlan,'current':None}

        return moved


    def apply_configuration(self,file,dir=None):
        """
        Apply a saved configuration to the current switch
        
        :param file: The name of file that contains the saved configuration
        :type  file: str

        :param dir: The directory path that the saved file is contained in. By
                    default, the configuration is looked for in CONFIG_DIR/configs
        :type  dir: str
        
        """
        diff = self.diff_configuration(file,dir=dir)
        
        for port,cfg in diff['ports'].items():
            destination = cfg['past']
            module_logger.info('Moving port {:} from {:} '\
                                'to {:}'.format(port,
                                                cfg['current'],
                                                destination))
            self.move_port(port,destination,verify=False)

        self.update()
        diff = self.diff_configuration(file,dir=dir)

        if diff['ports']:
            for port in diff['ports'].keys():
                module_logger.warning('{:} was not moved the correct VLAN') 


    def _surveyer(self):
        """
        Return survey object based on type attribute
        """
        try:
            survey_type = switch_types[self.type]
        except KeyError:
            raise ValueError('{:} is not a valid switch type'.format(self.type))

        surveyer = survey_type(self._user,self._pw,self._enablepw,
                               port=self._port,
                               timeout=self.timeout)
        return surveyer


    def _load_host(self,host):
        """
        Return a Host object for a device with name host
        """
        return self._nc.find_hosts(host,as_object=True)


class Vlan(object):

    _devices = {}

    """
    An object to represent a single VLAN on the switch

    :param vlan_no: The number associated with each VLAN
    :type  vlan_no: str

    :param ports: A list of ports on the VLAN
    :type  ports: list

    :param switch: The parent switch object
    :type  switch: Switch
    """
    def __init__(self,vlan_no,ports,switch=None):
        self._vlan_no = vlan_no
        self._switch  = switch
        self._unknown = {}
        self._nodes   = []
        self.ports   = ports

    
    @property
    def unknown_devices(self):
        """
        Return a list of unknown ethernet addresses
        """
        if not self._unknown:
            return None
        else:
            return self._unknown


    @property
    def devices(self):
        """
        Return devices found on VLAN
        """
        if self._devices:
            return sorted(self._devices.keys())   
        else:
            return []


    @property
    def subnet(self):
        """
        Return subnet for VLAN number
        """
        subnet_file = path.join(CONFIG_DIR, 'subnets.json')
        if path.exists(subnet_file):
            subnets = simplejson.load(open(subnet_file,'r'))
            try:
                subnet = subnets[str(self._vlan_no)]
            except KeyError:
                module_logger.warning('VLAN {:} is not associated with '\
                                    'a specific subnet'.format(self._vlan_no))
                subnet = None

            return subnet
        else:
            module_logger.critical('Unable to locate subnet JSON file')
            return None
        

    def survey(self): 
        """
        Find devices on this VLAN who belong to the wrong subnet
        
        This function looks at all of the devices found on the VLAN and
        determines whether the device is on the correct subnet by comparing the
        name of the subnet associated with the VLAN to the information in
        NetConfig

        :return: A list of devices on the wrong subnet
        :rtype: list
        """
        misplaced = []
        subnet    = self.subnet

        for device in self.devices:
            host = self._switch._load_host(device)
            if host.subnet != subnet:
                module_logger.warning('{:} is not on the correct '\
                                      'subnet, it should be on '\
                                      '{:}'.format(device,host.subnet))
                misplaced.append(device)
            else:
                module_logger.debug('{:} on the correct subnet'.format(device))
                
        return misplaced
