from PyQt5 import QtCore, QtGui
from PyQt5.QtWidgets import QTableWidget,QTableWidgetItem,QSizePolicy,QWidget,QCheckBox,QHBoxLayout
from PyQt5.QtCore import pyqtSignal
import functools

class VlanWidget(QTableWidget):

    _column_names = ('Port', 'VLAN', 'Device Name', 'Ethernet Address', 'PoE State', 'Comment')
    PORTCOL = 0
    VLANCOL = 1
    DEVCOL  = 2
    MACCOL  = 3
    POECOL  = 4
    CMTCOL  = 5
    set_power = pyqtSignal(str,int)
    set_name = pyqtSignal(str,str)

    """
    Table to display a group of Ports
    """
    def __init__(self,parent=None):
        self._ports = []
        self._power = {}
        self._labels = {}
        self._devices = {}
        self._portWidgets = {}
        
        super(VlanWidget,self).__init__(0,len(self._column_names),parent=parent)
        self.setHorizontalHeaderLabels(self._column_names)
        self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.cellChanged.connect(self.onCellChanged)

    def onCellChanged(self, row, column):
        if column == self.CMTCOL:
            port = self.item(row, self.PORTCOL)
            new_name = self.item(row, column).text()
            if new_name != self._labels[row]:
                self.set_name.emit(port.text(), new_name)

    def onPowerChanged(self, row, state):
        port = self.item(row, self.PORTCOL)
        new_pwr = 1 if state == QtCore.Qt.Checked else 0
        if new_pwr != self._power[row]:
            self.set_power.emit(port.text(), new_pwr)

    def add_ports(self,ports,vlans,power,labels):
        """
        Add a list of port information to the table
        """
        self.clearContents()
        self._ports = ports
        for (i,port) in enumerate(ports):
            if port in power.keys():
                pwr = power[port]
            else:
                pwr = ("Off", "Non-PD")
            if port in labels.keys():
                lbl = labels[port]
            else:
                lbl = ""
            self.add_port(port, vlans[i], pwr, lbl)
#        self.resizeColumnsToContents()
    
    def add_port(self,port,vlan,power,label):
        """
        Add a port to the table
        """
        new_row    = self.rowCount()
        self.insertRow(new_row)

        i = QTableWidgetItem(port)
        i.setFlags(QtCore.Qt.ItemIsEnabled|QtCore.Qt.ItemIsSelectable)
        self._portWidgets[port] = i
        self.setItem(new_row,self.PORTCOL,i)

        i = QTableWidgetItem(vlan)
        i.setFlags(QtCore.Qt.ItemIsEnabled|QtCore.Qt.ItemIsSelectable)
        self.setItem(new_row,self.VLANCOL,i)

        i = QTableWidgetItem("")
        i.setFlags(QtCore.Qt.ItemIsEnabled|QtCore.Qt.ItemIsSelectable)
        self.setItem(new_row,self.DEVCOL,i)

        i = QTableWidgetItem("")
        i.setFlags(QtCore.Qt.ItemIsEnabled|QtCore.Qt.ItemIsSelectable)
        self.setItem(new_row,self.MACCOL,i)

        self._power[new_row] = 1 if power[1] == "On" else 0
        if power[1] != 'Non-PD':
            cw = QWidget(self)
            cb = QCheckBox(cw)
            cb.setChecked(True if power[1] == "On" else False)
            cb.stateChanged.connect(functools.partial(self.onPowerChanged, new_row))
            l = QHBoxLayout(cw)
            l.addWidget(cb)
            l.setAlignment(QtCore.Qt.AlignCenter);
            l.setContentsMargins(0,0,0,0)
            self.setCellWidget(new_row,self.POECOL,cw);
        else:
            b = QTableWidgetItem()
            b.setFlags(QtCore.Qt.NoItemFlags)
            self.setItem(new_row,self.POECOL,b)
        self._labels[new_row] = label
        i = QTableWidgetItem(label)
        i.setFlags(QtCore.Qt.ItemIsEnabled|QtCore.Qt.ItemIsSelectable|QtCore.Qt.ItemIsEditable)
        self.setItem(new_row,self.CMTCOL,i)

    def add_devices(self,devices):
        """
        Add a dictionary of devices to the Table
        """
        self._devices = devices
        for device,device_info in self._devices.items():
            self.add_device(device_info['ethernet_address'],
                            device_info['port'],
                            device_info['vlan'],
                            device = device)
        self.resizeColumnsToContents()


    def add_device(self,mac,port,vlan,device=''):
        """
        Add a device to the table
        """
        row = self._portWidgets[port].row()
        i = self.item(row, self.DEVCOL)
        i.setText(device)
        i = self.item(row, self.MACCOL)
        i.setText(mac)

    
    def add_unknown(self,macs):
        """
        Add a dictionary of mac addresses to the table.
        """
        self._ethernet = macs
        for mac,device_info in self._ethernet.items():
            self.add_device(mac,
                            device_info['port'],
                            device_info['vlan'])
    

    def select_port(self,port):
        """
        Select a port
        """
        if port in self._portWidgets:
            row = self._portWidgets[port].row()
            self.selectRow(row)


    @QtCore.pyqtSlot(str)
    def highlight_device(self,device):
        if device in self._devices.keys():
            port = self._devices[str(device)]['port']
            row = self._portWidgets[port].row()
            for i in range(len(self._column_names)):
                item = self.item(row, i)
                if item:
                    item.setBackground(QtGui.QBrush(QtCore.Qt.yellow))

    def refresh_port(self, port, mac, name, dname, pwr):
        row = self._portWidgets[port].row()
        self._labels[row] = name
        self._power[row] = pwr
        i = self.item(row, self.DEVCOL)
        i.setText(dname)
        i = self.item(row, self.MACCOL)
        i.setText(mac)
        if pwr != 'Non-PD':
            cw = QWidget(self)
            cb = QCheckBox(cw)
            cb.setChecked(True if pwr == "On" else False)
            cb.stateChanged.connect(functools.partial(self.onPowerChanged, row))
            l = QHBoxLayout(cw)
            l.addWidget(cb)
            l.setAlignment(QtCore.Qt.AlignCenter);
            l.setContentsMargins(0,0,0,0)
            self.setCellWidget(row,self.POECOL,cw);
        else:
            b = QTableWidgetItem()
            b.setFlags(QtCore.Qt.NoItemFlags)
            self.setItem(row,self.POECOL,b)
        i = self.item(row, self.CMTCOL)
        i.setText(name)
