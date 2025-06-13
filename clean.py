#!/usr/bin/env python3
"""
iSED ESR Analyzer Communication Handler
======================================
Handles serial communication with iSED automated ESR analyzers following LIS2-A2 protocol.
The iSED is the master device - this script waits for data transmissions.

Protocol Flow:
1. iSED sends ENQ (enquiry)
2. Host responds with ACK (acknowledge) 
3. iSED sends data frames with STX...DATA...ETX+checksum
4. Host validates checksum and responds ACK/NAK
5. iSED sends EOT (end of transmission)

Author: Medical Lab Integration Team
Date: 2025
"""

import serial
import serial.tools.list_ports
import sys
import logging
from datetime import datetime
import json
from pathlib import Path

# Configure logging for easy debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'ised_log_{datetime.now().strftime("%Y%m%d")}.log')
    ]
)
logger = logging.getLogger(__name__)

# iSED Protocol Control Characters (from specification)
class ProtocolChars:
    ENQ = b'\x05'   # Enquiry - iSED requests to send data
    ACK = b'\x06'   # Acknowledge - Host accepts data
    NAK = b'\x15'   # Negative Acknowledge - Host rejects data
    STX = b'\x02'   # Start of Text - Begin data frame
    ETX = b'\x03'   # End of Text - End data frame
    EOT = b'\x04'   # End of Transmission - iSED finished sending
    CR = b'\x0D'    # Carriage Return
    LF = b'\x0A'    # Line Feed
    XON = b'\x11'   # Resume transmission
    XOFF = b'\x13'  # Pause transmission

# ESR Error Codes (from specification)
ESR_ERROR_CODES = {
    '-1': 'No flow detected',
    '-2': 'No spike detected', 
    '-3': 'Reverse flow detected',
    '-4': 'Insufficient data points',
    '-5': 'Sample too dark',
    '-7': 'Sample too clear',
    '-8': 'Withdrawal error',
    '-9': 'Flow in error',
    '-10': 'Flow out error',
    '-11': 'Acquisition error',
    '-12': 'Trigger delay error'
}

class iSEDHandler:
    def __init__(self):
        self.serial_port = None
        self.current_session = self._init_session()
        self.frame_timeout = 10  # seconds
        self.max_retries = 6     # per specification
        
    def _init_session(self):
        """Initialize a new data session"""
        return {
            'header': {},
            'patients': [],
            'orders': [],
            'results': [],
            'session_start': datetime.now().isoformat(),
            'session_id': datetime.now().strftime("%Y%m%d_%H%M%S")
        }
    
    def select_serial_port(self):
        """Interactive serial port selection"""
        ports = serial.tools.list_ports.comports()
        
        if not ports:
            logger.error("No serial ports found!")
            sys.exit(1)
        
        print("\n=== Available Serial Ports ===")
        for i, port in enumerate(ports, 1):
            print(f"{i:2d}. {port.device:10s} - {port.description}")
        
        while True:
            try:
                choice = input(f"\nSelect port (1-{len(ports)}): ").strip()
                port_idx = int(choice) - 1
                
                if 0 <= port_idx < len(ports):
                    selected = ports[port_idx].device
                    logger.info(f"Selected port: {selected}")
                    return selected
                    
                print(f"Please enter a number between 1 and {len(ports)}")
                
            except (ValueError, KeyboardInterrupt):
                print("\nExiting...")
                sys.exit(0)
    
    def connect(self, port=None):
        """Establish serial connection to iSED analyzer"""
        if not port:
            port = self.select_serial_port()
            
        try:
            # iSED specification: 9600 baud, 8N1, XON/XOFF flow control
            self.serial_port = serial.Serial(
                port=port,
                baudrate=9600,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.frame_timeout,
                xonxoff=True  # Hardware flow control per spec
            )
            
            logger.info(f"Connected to iSED analyzer on {port}")
            logger.info("Ready to receive data (iSED is master device)")
            return True
            
        except serial.SerialException as e:
            logger.error(f"Failed to connect to {port}: {e}")
            return False
    
    def listen_for_data(self):
        """Main listening loop - waits for iSED to initiate communication"""
        logger.info("Listening for iSED transmissions... (Press Ctrl+C to exit)")
        
        try:
            while True:
                # Wait for ENQ from iSED (iSED is always master)
                data = self.serial_port.read(1)
                
                if data == ProtocolChars.ENQ:
                    logger.info("📡 ENQ received from iSED - starting data reception")
                    self._handle_transmission()
                elif data:
                    logger.debug(f"Unexpected data received: {data.hex()}")
                    
        except KeyboardInterrupt:
            logger.info("User interrupted - shutting down")
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            self.disconnect()
    
    def _handle_transmission(self):
        """Handle complete data transmission from iSED"""
        try:
            # Send ACK to accept transmission
            self.serial_port.write(ProtocolChars.ACK)
            logger.info("✅ ACK sent - ready for data frames")
            
            frame_count = 0
            
            while True:
                # Read complete frame (ends with LF)
                frame_data = self.serial_port.read_until(ProtocolChars.LF)
                
                if not frame_data:
                    logger.warning("⏰ Timeout waiting for frame")
                    break
                
                # Check for end of transmission
                if frame_data.startswith(ProtocolChars.EOT):
                    logger.info("🏁 EOT received - transmission complete")
                    self.serial_port.write(ProtocolChars.ACK)
                    self._finalize_session()
                    break
                
                # Process STX data frames
                if frame_data.startswith(ProtocolChars.STX):
                    frame_count += 1
                    success = self._process_frame(frame_data, frame_count)
                    
                    if success:
                        self.serial_port.write(ProtocolChars.ACK)
                        logger.info(f"✅ Frame {frame_count} processed successfully")
                    else:
                        self.serial_port.write(ProtocolChars.NAK)
                        logger.error(f"❌ Frame {frame_count} rejected - will be retransmitted")
                
        except Exception as e:
            logger.error(f"Error handling transmission: {e}")
    
    def _process_frame(self, frame_data, frame_num):
        """Process individual data frame with checksum verification"""
        try:
            # Verify checksum first
            if not self._verify_checksum(frame_data):
                logger.error(f"Checksum verification failed for frame {frame_num}")
                return False
            
            # Extract frame components
            frame_number = chr(frame_data[1])  # Frame number after STX
            stx_pos = frame_data.find(ProtocolChars.STX)
            etx_pos = frame_data.find(ProtocolChars.ETX)
            
            # Extract data message
            data_section = frame_data[stx_pos + 2:etx_pos].decode('ascii', errors='ignore')
            data_section = data_section.rstrip('\r')  # Remove trailing CR
            
            logger.debug(f"Frame {frame_number}: {data_section[:80]}...")
            
            # Process each record in the frame
            records = [r for r in data_section.split('\r') if r]
            
            for record in records:
                self._process_record(record)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return False
    
    def _verify_checksum(self, frame_data):
        """Verify frame checksum according to iSED specification"""
        try:
            stx_pos = frame_data.find(ProtocolChars.STX)
            etx_pos = frame_data.find(ProtocolChars.ETX)
            
            if stx_pos == -1 or etx_pos == -1:
                return False
            
            # Extract received checksum (2 hex chars after ETX)
            checksum_start = etx_pos + 1
            received_checksum = frame_data[checksum_start:checksum_start + 2].decode('ascii')
            
            # Calculate checksum: sum of bytes from frame_number to ETX (inclusive)
            data_for_checksum = frame_data[stx_pos + 1:etx_pos + 1]
            calculated_sum = sum(data_for_checksum) % 256
            calculated_checksum = f"{calculated_sum:02X}"
            
            is_valid = received_checksum.upper() == calculated_checksum.upper()
            
            if not is_valid:
                logger.debug(f"Checksum mismatch: received={received_checksum}, calculated={calculated_checksum}")
            
            return is_valid
            
        except:
            return False
    
    def _process_record(self, record):
        """Process individual record based on type"""
        if not record:
            return
            
        record_type = record[0]
        fields = record.split('|')
        
        processors = {
            'H': self._process_header,
            'P': self._process_patient, 
            'O': self._process_order,
            'R': self._process_result,
            'L': self._process_terminator
        }
        
        processor = processors.get(record_type)
        if processor:
            processor(fields)
        else:
            logger.warning(f"Unknown record type: {record_type}")
    
    def _process_header(self, fields):
        """Process Header record (H) - analyzer information"""
        # Parse sender info: Alcor^iSED^SWver^instrument#
        sender_parts = fields[4].split('^') if len(fields) > 4 else []
        
        header = {
            'manufacturer': sender_parts[0] if len(sender_parts) > 0 else 'Unknown',
            'product': sender_parts[1] if len(sender_parts) > 1 else 'Unknown',
            'software_version': sender_parts[2] if len(sender_parts) > 2 else 'Unknown',
            'instrument_id': sender_parts[3] if len(sender_parts) > 3 else 'Unknown',
            'message_datetime': fields[13] if len(fields) > 13 else '',
            'processing_id': fields[11] if len(fields) > 11 else '',
            'version_number': fields[12] if len(fields) > 12 else ''
        }
        
        self.current_session['header'] = header
        logger.info(f"🔬 Analyzer: {header['manufacturer']} {header['product']} "
                   f"v{header['software_version']} (ID: {header['instrument_id']})")
    
    def _process_patient(self, fields):
        """Process Patient record (P) - patient demographics"""
        patient = {
            'sequence': fields[1] if len(fields) > 1 else '',
            'patient_id': fields[3] if len(fields) > 3 else '',  # Lab assigned ID
            'patient_name': fields[5] if len(fields) > 5 else '',
            'birthdate': fields[7] if len(fields) > 7 else '',
            'sex': fields[8] if len(fields) > 8 else '',
            'attending_physician': fields[13] if len(fields) > 13 else ''
        }
        
        self.current_session['patients'].append(patient)
        logger.info(f"👤 Patient: {patient['patient_name']} (ID: {patient['patient_id']})")
    
    def _process_order(self, fields):
        """Process Order record (O) - test orders"""
        # Parse sample info: Sample_ID^rotor_location
        sample_parts = fields[2].split('^') if len(fields) > 2 else []
        
        order = {
            'sequence': fields[1] if len(fields) > 1 else '',
            'sample_id': sample_parts[0] if len(sample_parts) > 0 else '',
            'rotor_location': sample_parts[1] if len(sample_parts) > 1 else '',
            'test_id': fields[4] if len(fields) > 4 else '',  # Should be ^^^ESR
            'report_type': fields[25] if len(fields) > 25 else ''
        }
        
        self.current_session['orders'].append(order)
        logger.info(f"🧪 Order: Sample {order['sample_id']} "
                   f"(Position: {order['rotor_location']}, Test: ESR)")
    
    def _process_result(self, fields):
        """Process Result record (R) - ESR test results"""
        result = {
            'sequence': fields[1] if len(fields) > 1 else '',
            'test_id': fields[2] if len(fields) > 2 else '',  # ^^^ESR^4537-7
            'value': fields[3] if len(fields) > 3 else '',
            'units': fields[4] if len(fields) > 4 else '',    # mm/h
            'abnormal_flag': fields[6] if len(fields) > 6 else '',  # < or >
            'status': fields[8] if len(fields) > 8 else '',   # P=Preliminary, X=Cannot do
            'test_start': fields[11] if len(fields) > 11 else '',
            'test_complete': fields[12] if len(fields) > 12 else '',
            'instrument_id': fields[13] if len(fields) > 13 else '',
            'interpretation': self._interpret_result(fields[3], fields[6]),
            'timestamp': datetime.now().isoformat()
        }
        
        self.current_session['results'].append(result)
        
        # Log result with interpretation
        status_emoji = "✅" if result['interpretation'].startswith('Normal') else "⚠️"
        logger.info(f"{status_emoji} ESR Result: {result['value']} {result['units']} "
                   f"({result['interpretation']}) [Instrument: {result['instrument_id']}]")
    
    def _interpret_result(self, value, abnormal_flag):
        """Interpret ESR result value and flags"""
        # Check for error codes (negative values)
        if value.startswith('-'):
            return ESR_ERROR_CODES.get(value, f'Unknown error: {value}')
        
        # Check range flags
        if abnormal_flag == '<':
            return 'Below range (< 1 mm/hr)'
        elif abnormal_flag == '>':
            return 'Above range (> 130 mm/hr)'
        
        # Normal numeric result
        try:
            numeric_value = float(value)
            return f'Normal measurement: {numeric_value} mm/hr'
        except ValueError:
            return f'Invalid format: {value}'
    
    def _process_terminator(self, fields):
        """Process Terminator record (L) - end of transmission"""
        termination_code = fields[2] if len(fields) > 2 else ''
        logger.info(f"🏁 Transmission terminated (Code: {termination_code})")
    
    def _finalize_session(self):
        """Save session data and prepare for next transmission"""
        try:
            self.current_session['session_end'] = datetime.now().isoformat()
            
            # Save detailed session data
            session_file = f"ised_session_{self.current_session['session_id']}.json"
            with open(session_file, 'w') as f:
                json.dump(self.current_session, f, indent=2)
            
            # Create and save summary
            summary = self._create_session_summary()
            summary_file = f"ised_summary_{self.current_session['session_id']}.json"
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
            
            logger.info(f"💾 Session saved: {len(self.current_session['results'])} results processed")
            logger.info(f"📊 Files created: {session_file}, {summary_file}")
            
            # Reset for next session
            self.current_session = self._init_session()
            
        except Exception as e:
            logger.error(f"Error saving session: {e}")
    
    def _create_session_summary(self):
        """Create human-readable session summary"""
        header = self.current_session.get('header', {})
        
        summary = {
            'session_info': {
                'session_id': self.current_session['session_id'],
                'start_time': self.current_session['session_start'],
                'end_time': self.current_session.get('session_end', ''),
                'analyzer': f"{header.get('manufacturer', 'N/A')} {header.get('product', 'N/A')}",
                'software_version': header.get('software_version', 'N/A'),
                'instrument_id': header.get('instrument_id', 'N/A')
            },
            'statistics': {
                'total_patients': len(self.current_session['patients']),
                'total_orders': len(self.current_session['orders']),
                'total_results': len(self.current_session['results']),
                'successful_tests': len([r for r in self.current_session['results'] 
                                       if r['interpretation'].startswith('Normal')]),
                'error_tests': len([r for r in self.current_session['results'] 
                                  if not r['interpretation'].startswith('Normal')])
            },
            'results': []
        }
        
        # Add individual results
        for i, result in enumerate(self.current_session['results']):
            # Find corresponding patient and order info
            patient = next((p for p in self.current_session['patients'] 
                          if p['sequence'] == result['sequence']), {})
            order = next((o for o in self.current_session['orders'] 
                        if o['sequence'] == result['sequence']), {})
            
            summary['results'].append({
                'test_number': i + 1,
                'patient_name': patient.get('patient_name', 'N/A'),
                'patient_id': patient.get('patient_id', 'N/A'),
                'sample_id': order.get('sample_id', 'N/A'),
                'esr_value': result['value'],
                'units': result['units'],
                'interpretation': result['interpretation'],
                'test_completed': result['test_complete'],
                'instrument_id': result['instrument_id']
            })
        
        return summary
    
    def disconnect(self):
        """Close serial connection"""
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            logger.info("🔌 Serial connection closed")

def main():
    """Main entry point"""
    print("="*60)
    print("iSED ESR Analyzer Communication Handler")
    print("Medical Laboratory Integration System")
    print("="*60)
    
    handler = iSEDHandler()
    
    try:
        if handler.connect():
            handler.listen_for_data()
    except Exception as e:
        logger.error(f"Application error: {e}")
    finally:
        handler.disconnect()

if __name__ == "__main__":
    main()