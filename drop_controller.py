#!/usr/bin/env python3
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER,
    MAIN_DISPATCHER, set_ev_cls)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4

class PacketDropController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures,
                CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        # Install table-miss: send unknown packets to controller
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(
            ofproto.OFPP_CONTROLLER,
            ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        # ── DROP RULE ──────────────────────────────────────────
        # Drop all traffic FROM h1 (10.0.0.1) TO h3 (10.0.0.3)
        # Priority 100 > default 0, so it matches first
        drop_match = parser.OFPMatch(
            eth_type=0x0800,   # IPv4
            ipv4_src='10.0.0.1',
            ipv4_dst='10.0.0.3'
        )
        self.add_flow(datapath, 100, drop_match, [])
        self.logger.info("DROP rule installed: h1→h3 blocked")

    def add_flow(self, datapath, priority,
                 match, actions, idle=0, hard=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = ([parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS, actions)]
                if actions else [])
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle,
            hard_timeout=hard)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn,
                MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        # Basic learning switch for non-dropped traffic
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        out_port = (self.mac_to_port[dpid].get(dst)
                    or ofproto.OFPP_FLOOD)

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(
                in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions)

        data = (msg.data
                if msg.buffer_id == ofproto.OFP_NO_BUFFER
                else None)
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions, data=data)
        datapath.send_msg(out)
