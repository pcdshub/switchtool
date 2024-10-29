import sys
import logging
from PyQt5 import QtGui,QtCore,QtWidgets
from PyQt5.QtCore import pyqtSlot,pyqtSignal,QTimer,QSettings
import functools

from .vlan import VlanWidget
from ...EpicsQT.qlogdisplay import QLogDisplay
from .. import dialogs
from ...switch.switch import Switch

class SwitchWidget(QtWidgets.QWidget):
    
    _vlan = {}
    
    misplaced = pyqtSignal(str)
    updated   = pyqtSignal()
    update_port = pyqtSignal(str, str, str, str, str, str)

    def __init__(self,switch,user=None,pw=None,timeout=1.0,parent=None):
        super(SwitchWidget,self).__init__(parent=parent)
        self.resize(660,700)

        self._switch = None
        self.switch_name = switch.split(".")[0]
        self.refresh_timeout = timeout * 3600000 # Now ms!

        self.settings = QSettings("SLAC", "switchtool")
        self.switch_label = QtWidgets.QLabel(switch)
        title_font = QtGui.QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        self.switch_label.setFont(title_font)

        self._vlanTab     = QtWidgets.QTabWidget(parent=self)
        self._vlanTab.setMovable(True)
        self._vlanTab.tabBar().tabMoved.connect(self.tabMoved)
        self._vlanList = None
        
        #Log Handler
        self.switch_log = logging.getLogger('psnet.switch')
        self.log = QLogDisplay()
        self.log.addLog(self.switch_log,level=logging.INFO)
        
        #Move  Layout
        self.utilities = QtWidgets.QGroupBox('Utilities')
        self.refresh_button = QtWidgets.QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.do_update)
        self.survey_button = QtWidgets.QPushButton('Survey')
        self.survey_button.clicked.connect(self.survey)
        self.move_button = QtWidgets.QPushButton('Move Port')
        self.move_button.clicked.connect(self.move_port)
        self.configure_button = QtWidgets.QPushButton('Auto Configure')
        self.configure_button.clicked.connect(self.auto_configure)
        self.write_memory_button = QtWidgets.QPushButton('Write Memory')
        self.write_memory_button.clicked.connect(self.write_memory)
        
        self.move_layout = QtWidgets.QHBoxLayout()
        self.move_layout.addWidget(self.refresh_button)
        self.move_layout.addWidget(self.survey_button)
        self.move_layout.addWidget(self.move_button)
        self.move_layout.addWidget(self.configure_button)
        self.move_layout.addWidget(self.write_memory_button)
        
        self.utilities.setLayout(self.move_layout)

        #Search Layout 
        self.portCombo = QtWidgets.QComboBox()
        self.portCombo.activated[str].connect(self.find_port)
        self.deviceCombo = QtWidgets.QComboBox()
        self.deviceCombo.activated[str].connect(self.find_device)
        self.deviceCombo.setFixedWidth(200)
        self.deviceLine = QtWidgets.QLineEdit()
        self.deviceCombo.setFixedWidth(200)
        self.deviceLine.returnPressed.connect(self.dlreturn)
        
        self.search_layout = QtWidgets.QHBoxLayout()
        self.search_layout.addStretch(2)
        self.search_layout.addWidget(QtWidgets.QLabel('Find Port: '))
        self.search_layout.addWidget(self.portCombo)
        self.search_layout.addStretch(1)
        self.search_layout.addWidget(QtWidgets.QLabel('Find Device: '))
        self.search_layout.addWidget(self.deviceCombo)
        self.search_layout.addStretch(1)
        self.search_layout.addWidget(self.deviceLine)
        self.search_layout.addStretch(2)
        
        #Overall Layout
        self.lay = QtWidgets.QVBoxLayout()
        self.lay.addWidget(self.switch_label,
                           alignment=QtCore.Qt.AlignCenter)
        self.lay.addWidget(self.log)
        self.lay.addWidget(self.utilities)
        self.lay.addLayout(self.search_layout)
        self.lay.addWidget(self._vlanTab)
        self.setLayout(self.lay)

        self.finddialog = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.need_refresh)
        self.repaint()
        QTimer.singleShot(100, functools.partial(self.initial_update, switch, user, pw));
        
    def initial_update(self, switch, user, pw):
        self._switch = PyQtSwitch(switch,user=user,pw=pw,enablepw=None,parent=self)
        self.updated.connect(self.refresh)
        self.update_port.connect(self.refresh_port)
        self._switch.update()

    def survey(self):
        """
        Survey the switch for devices on the wrong subnet
        """
        devices = self._switch.survey()
        for device in devices:
            self.misplaced.emit(device)

    @pyqtSlot()
    def need_refresh(self):
        self.timer.stop()
        self.refresh_button.setStyleSheet("color:white;background-color:red;")
        self.switch_log.warning("Timer expired: Refresh recommended!!")

    @pyqtSlot(str)
    def find_device(self,device):
        """
        Find a device on the switch and select it
        """
        device = str(device)
        vlan,port = self._switch.find_device(device)
        if vlan and port:
            self.select_vlan(vlan,port=port)

    """
    The finddialog is a nonmodal dialog!  So dlreturn just creates and shows it.
    
    If there is already one open, we close it.
    
    If the dialog accepts (clicks OK), we close it here.
    If it closes, we forget about it.
    """

    @pyqtSlot()
    def dlreturn(self):
        device = self.deviceLine.text()
        if self.finddialog:
            self.finddialog.close()
        l = self._switch.find_device_substr(device)
        ll = len(l)
        if ll == 0:
            QtWidgets.QMessageBox.critical(None,
                                           "Warning", "No matches for '%s'!" % device,
                                           QtWidgets.QMessageBox.Ok, QtWidgets.QMessageBox.Ok)
        elif ll == 1:
            self.select_vlan(l[0][1],port=l[0][2])
        else:
            self.finddialog = dialogs.FindDialog(device, l, parent=self)
            self.finddialog.accepted.connect(self.FDaccept)
            self.finddialog.closing.connect(self.FDclose)
            self.finddialog.select.connect(self.FDselect)
            self.finddialog.show()

    @pyqtSlot()
    def FDaccept(self):
        fd = self.finddialog
        fd.close()

    @pyqtSlot()
    def FDclose(self):
        self.finddialog = None

    @pyqtSlot(str, str)
    def FDselect(self, vlan, port):
        self.select_vlan(vlan, port)

    @pyqtSlot(str)
    def find_port(self,port):
        """
        Find a port on the switch and select it
        """
        port = str(port)
        vlan = self._switch.find_port(port)
        if vlan:
            self.select_vlan(vlan,port=port)

    @pyqtSlot(int, int)
    def tabMoved(self, start, dest):
        self._vlanList.insert(dest, self._vlanList.pop(start))
        self.settings.setValue("vlan_order/%s" % self.switch_name, self._vlanList)

    @pyqtSlot()
    def do_update(self):
        self._switch.update()

    @pyqtSlot(str, int)
    def do_set_power(self, port, state):
        self._switch.set_power(port, state)

    @pyqtSlot(str, str)
    def do_set_name(self, port, name):
        self._switch.set_name(port, name)

    @pyqtSlot()
    def refresh(self):
        """
        Reload all of the VLAN information
        """
        if self._vlanList is not None:
            curtab = self._vlanTab.tabBar().currentIndex()
        else:
            curtab = 0
        self._vlanTab.clear()
        self.portCombo.clear()
        self.deviceCombo.clear()
        self.deviceLine.clear()
        alltabs = {}
        allsubs = {}
        allvlan = {}
        
        switch = VlanWidget(parent=self)
        self._complete = switch
        switch.set_power.connect(self.do_set_power)
        switch.set_name.connect(self.do_set_name)
        self.misplaced.connect(switch.highlight_device)
        plist = self._switch.ports
        switch.add_ports(plist, self._switch.find_vlans(plist),
                         self._switch.power(), self._switch.labels())
        d = self._switch.devices
        switch.add_devices(d)
        c = QtWidgets.QCompleter(d)
        # Popup or Inline?!?
        c.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.deviceLine.setCompleter(c)
        switch.add_unknown(self._switch.unknown_devices)
        switch.resize(switch.maximumSize())
        alltabs[-1] = (switch,'Complete Switch')
        allsubs["All"] = -1
        allvlan[-1] = "All"

        for vlan_no,subnet  in self._switch.subnets:
            tab = 'VLAN {:} - {:}'.format(vlan_no,subnet)
            vlan = getattr(self._switch,
                           self._switch._vlan_alias.format(vlan_no))
            vlan_table = VlanWidget(parent=self)
            vlan_table.set_power.connect(self.do_set_power)
            vlan_table.set_name.connect(self.do_set_name)
            self.misplaced.connect(vlan_table.highlight_device)
            self._vlan[vlan_no] = vlan_table

            plist = vlan.ports
            vlan_table.add_ports(plist, self._switch.find_vlans(plist),
                                 self._switch.power(), self._switch.labels())
            vlan_table.add_devices(vlan._devices)
            vlan_table.add_unknown(vlan._unknown)
            vlan_table.resize(vlan_table.maximumSize())
            vn = int(vlan_no)
            alltabs[vn] = (vlan_table, tab)
            # Sigh... subnet can be None for vlan 1!
            allsubs[str(subnet)] = vn
            allvlan[vn] = str(subnet)

        vlist = [k for k in alltabs.keys()]
        vlist.sort()
        nl = []

        #
        # Do we have a preferred vlan order?
        #
        if self._vlanList is None:
            # First pass: try to get a saved order.
            self._vlanList = self.settings.value("vlan_order/%s" % self.switch_name)

            if self._vlanList is not None:
                self._vlanList = [int(vl) for vl in self._vlanList]
            else:
                # No saved list, so second pass: use the switch name to
                # try to build a decent order.
                #
                # Let's say:
                #    All
                #    CDS&FEZ for this hutch
                #    DMZ
                #    LAS CDS
                #    Other CDS&FEZ
                #
                vl = []
                vl.append(-1)
                try:
                    h = self.switch_name.split("-")[1].lower()
                except:
                    h = "NOHUTCH"
                sub = "cds-%s.pcdsn" % h
                if sub in allsubs.keys():
                    vl.append(allsubs[sub])
                sub = "fez-%s.pcdsn" % h
                if sub in allsubs.keys():
                    vl.append(allsubs[sub])
                sub = "ics.pcdsn"
                if sub in allsubs.keys():
                    vl.append(allsubs[sub])
                sub = "cds-las.pcdsn"
                if sub in allsubs.keys():
                    vl.append(allsubs[sub])
                for v in vlist:
                    if v not in vl and allvlan[v][:3] == 'cds':
                        vl.append(v)
                for v in vlist:
                    if v not in vl and allvlan[v][:3] == 'fez':
                        vl.append(v)
                self._vlanList = vl    
            
        # Now, go through the prefered vlan list order.  Add the
        # vlans that exist on this switch in this order, and then
        # append the vlans on the switch not in this list in numeric
        # order.
        for k in self._vlanList:
            if k in vlist:
                nl.append(k)
        for k in vlist:
            if k not in nl:
                nl.append(k)
        self._vlanList = nl
        self.settings.setValue("vlan_order/%s" % self.switch_name, self._vlanList)

        for k in self._vlanList:
            (vlan_table, tab) = alltabs[k]
            self._vlanTab.addTab(vlan_table,tab)
        self._vlanTab.tabBar().setCurrentIndex(curtab)

        devices = []
        ports   = []

        for vlan in self._switch._vlan:
            for device in vlan.devices:
                devices.append(device)
            for port in vlan.ports:
                ports.append(port)
        
        self.portCombo.addItems(sorted(ports))
        self.deviceCombo.addItems(sorted(devices))

        self.timer.start(self.refresh_timeout)
        self.refresh_button.setStyleSheet("color:black;")

    @pyqtSlot(str, str, str, str, str, str)
    def refresh_port(self, port, vlan, mac, name, dname, pwr):
        self._complete.refresh_port(port, mac, name, dname, pwr)
        self._vlan[vlan].refresh_port(port, mac, name, dname, pwr)

    def select_vlan(self,vlan_no,port=None):
        """
        Select a VLAN in the tab
        """
        if vlan_no in self._vlan.keys():
            vlan = self._vlan[vlan_no]
            self._vlanTab.setCurrentWidget(vlan)
            if port:
                self._vlanTab.currentWidget().select_port(port)


    def move_port(self):
        """
        Launch Dialog to move port
        """

        dialog  = dialogs.MoveDialog(self._switch.ports,
                                     self._switch.devices,
                                     self._switch.subnets,
                                     parent=self) 
        if dialog.exec_():
            port,vlan = dialog.current_move()
            self._switch.move_port(port,vlan)

    
    def auto_configure(self): 
        """
        Launch the Auto-Configuration dialog
        """
        devices = self._switch.survey()
        

        if devices:
            ports   = [self._switch.find_device(dev)[1] for dev in devices]
            subnets = [self._switch.find_subnet_for_host(dev)[1] for dev in devices]
            devices = zip(devices,ports,subnets)
        
        dialog = dialogs.ConfigureDialog(devices,parent=self)

        if dialog.exec_():
            approved = dialog.approved_moves
            for move in approved:
                device,port,subnet = move
                self._switch.move_device(device,subnet=subnet)

    def write_memory(self):
        """
        Run the "write memory" command to make the switch config persist on boot.
        """
        self._switch.write_memory()


class PyQtSwitch(Switch):
    def __init__(self,switchname,user='admin',pw=None,enablepw=None,parent=None):
        self.parent = parent
        super(PyQtSwitch,self).__init__(switchname,user=user,pw=pw,enablepw=enablepw)
        
    def update(self):
        """
        Update switch configuration and emit signal
        """
        super(PyQtSwitch,self).update()
        if self.parent:
            self.parent.updated.emit()

    def update_port_gui(self, port, vlan, mac, name, dname, pwr):
        if self.parent:
            self.parent.update_port.emit(port, vlan, mac, name, dname, pwr)
