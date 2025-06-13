import serial
import serial.tools.list_ports
import sys
import logging
from datetime import datetime
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def select_serial_port():
    """Lists available serial ports and prompts user to select one"""
    # Get list of available ports
    ports = serial.tools.list_ports.comports()
    
    if not ports:
        print("No serial ports found!")
        sys.exit(1)
    
    print("\nAvailable serial ports:")
    for i, port in enumerate(ports, 1):
        print(f"{i}. {port.device} - {port.description}")
    
    # Prompt user to select
    while True:
        try:
            selection = input("\nSelect port number (1-{}): ".format(len(ports)))
            port_index = int(selection) - 1
            if 0 <= port_index < len(ports):
                selected_port = ports[port_index].device
                print(f"Selected: {selected_port}")
                return selected_port
            print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a number.")

selected_port = select_serial_port()

# Serial connection
ser = serial.Serial(port=selected_port, baudrate=9600, bytesize=serial.EIGHTBITS, 
                   parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, 
                   timeout=10, xonxoff=True)

# Control characters (iSED specification)
ENQ = b'\x05'  # ENQ - Enquiry
ACK = b'\x06'  # ACK - Acknowledge
NAK = b'\x15'  # NAK - Negative Acknowledge
STX = b'\x02'  # STX - Start of Text
ETX = b'\x03'  # ETX - End of Text
EOT = b'\x04'  # EOT - End of Transmission
CR = b'\x0D'   # Carriage Return
LF = b'\x0A'   # Line Feed
XON = b'\x11'  # XON - Resume transmission
XOFF = b'\x13' # XOFF - Pause transmission

# Data storage for current session
current_session = {
    'header': {},
    'patients': [],
    'orders': [],
    'results': [],
    'session_start': datetime.now().isoformat()
}

def process_ised_data():
    """Main processing loop for iSED data communication"""
    logger.info("Starting iSED data processing...")
    
    while True:
        try:
            # Wait for ENQ from iSED (iSED is master)
            data = ser.read(1)
            if data == ENQ:
                logger.info("Received ENQ from iSED, sending ACK")
                ser.write(ACK)
                
                # Process data frames until EOT
                frame_count = 0
                while True:
                    # Read until we get a complete frame (ending with LF)
                    frame = ser.read_until(LF)
                    
                    if not frame:
                        logger.warning("Timeout occurred while waiting for frame")
                        break
                    
                    # Check if this is EOT
                    if frame.startswith(EOT):
                        logger.info("Received EOT, transmission complete")
                        ser.write(ACK)
                        break
                    
                    # Process STX frames
                    if frame.startswith(STX):
                        frame_count += 1
                        logger.debug(f"Processing frame {frame_count}")
                        
                        if verify_checksum(frame):
                            logger.info(f"Frame {frame_count} checksum verified, sending ACK")
                            ser.write(ACK)
                            process_frame(frame)
                        else:
                            logger.error(f"Frame {frame_count} checksum failed, sending NAK")
                            ser.write(NAK)
                            # iSED will retransmit the same frame (same frame number)
                    
        except KeyboardInterrupt:
            logger.info("Process interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error in processing: {e}")
            continue

def verify_checksum(frame):
    """
    Verify iSED frame checksum
    Checksum = sum of ASCII values from after STX to ETX (inclusive), modulo 256
    Format: <STX>1...Data...<CR><ETX>X1X2<CR><LF>
    """
    try:
        # Find positions of key markers
        stx_pos = frame.find(STX)
        etx_pos = frame.find(ETX)
        
        if stx_pos == -1 or etx_pos == -1:
            logger.error("Invalid frame format - missing STX or ETX")
            return False
        
        # Extract checksum (2 hex chars after ETX)
        checksum_start = etx_pos + 1
        received_checksum = frame[checksum_start:checksum_start + 2].decode('ascii')
        
        # Calculate checksum from frame number to ETX (inclusive)
        # This includes: frame_number + data + CR + ETX
        data_for_checksum = frame[stx_pos + 1:etx_pos + 1]
        calculated_sum = sum(data_for_checksum) % 256
        calculated_checksum = f"{calculated_sum:02X}"
        
        logger.debug(f"Received checksum: {received_checksum}, Calculated: {calculated_checksum}")
        return received_checksum.upper() == calculated_checksum.upper()
        
    except Exception as e:
        logger.error(f"Checksum verification error: {e}")
        return False

def process_frame(frame):
    """Process iSED data frame"""
    try:
        # Extract frame number (byte after STX)
        frame_number = chr(frame[1])
        logger.info(f"Processing frame number: {frame_number}")
        
        # Extract data message (between frame number and ETX)
        stx_pos = frame.find(STX)
        etx_pos = frame.find(ETX)
        data_message = frame[stx_pos + 2:etx_pos].decode('ascii')
        
        # Remove trailing CR if present
        if data_message.endswith('\r'):
            data_message = data_message[:-1]
        
        # Split into records (separated by CR)
        records = data_message.split('\r')
        
        for record in records:
            if not record:
                continue
                
            record_type = record[0]
            logger.debug(f"Processing record type: {record_type} - {record[:50]}...")
            
            if record_type == 'H':
                process_header_record(record)
            elif record_type == 'P':
                process_patient_record(record)
            elif record_type == 'O':
                process_order_record(record)
            elif record_type == 'R':
                process_result_record(record)
            elif record_type == 'L':
                process_terminator_record(record)
            else:
                logger.warning(f"Unknown record type: {record_type}")
                
    except Exception as e:
        logger.error(f"Error processing frame: {e}")

def process_header_record(record):
    """Process iSED Header record (H)"""
    fields = record.split('|')
    
    # Parse sender name field (Alcor^iSED^SWver^instrument#)
    sender_info = fields[4].split('^') if len(fields) > 4 else []
    
    header_info = {
        'record_type': fields[0] if len(fields) > 0 else '',
        'delimiter_definition': fields[1] if len(fields) > 1 else '',
        'message_control_id': fields[2] if len(fields) > 2 else '',
        'access_password': fields[3] if len(fields) > 3 else '',
        'manufacturer': sender_info[0] if len(sender_info) > 0 else '',
        'product_name': sender_info[1] if len(sender_info) > 1 else '',
        'software_version': sender_info[2] if len(sender_info) > 2 else '',
        'instrument_id': sender_info[3] if len(sender_info) > 3 else '',
        'sender_address': fields[5] if len(fields) > 5 else '',
        'reserved': fields[6] if len(fields) > 6 else '',
        'sender_phone': fields[7] if len(fields) > 7 else '',
        'characteristics': fields[8] if len(fields) > 8 else '',
        'receiver_id': fields[9] if len(fields) > 9 else '',
        'comments': fields[10] if len(fields) > 10 else '',
        'processing_id': fields[11] if len(fields) > 11 else '',  # Should be 'P'
        'version_number': fields[12] if len(fields) > 12 else '',  # Should be 'E 1394-97'
        'message_datetime': fields[13] if len(fields) > 13 else ''   # YYYYMMDDHHMMSS
    }
    
    current_session['header'] = header_info
    logger.info(f"Header processed: {header_info['manufacturer']} {header_info['product_name']} "
                f"v{header_info['software_version']} (ID: {header_info['instrument_id']})")

def process_patient_record(record):
    """Process iSED Patient record (P)"""
    fields = record.split('|')
    
    patient_info = {
        'record_type': fields[0] if len(fields) > 0 else '',
        'sequence_number': fields[1] if len(fields) > 1 else '',
        'practice_patient_id': fields[2] if len(fields) > 2 else '',
        'laboratory_patient_id': fields[3] if len(fields) > 3 else '',  # Patient ID (max 30)
        'patient_id_3': fields[4] if len(fields) > 4 else '',
        'patient_name': fields[5] if len(fields) > 5 else '',
        'mother_maiden_name': fields[6] if len(fields) > 6 else '',
        'birthdate': fields[7] if len(fields) > 7 else '',
        'patient_sex': fields[8] if len(fields) > 8 else '',
        'patient_race': fields[9] if len(fields) > 9 else '',
        'patient_address': fields[10] if len(fields) > 10 else '',
        'reserved': fields[11] if len(fields) > 11 else '',
        'patient_phone': fields[12] if len(fields) > 12 else '',
        'attending_physician_id': fields[13] if len(fields) > 13 else '',
        'special_field_1': fields[14] if len(fields) > 14 else '',
        'special_field_2': fields[15] if len(fields) > 15 else '',
        'patient_height': fields[16] if len(fields) > 16 else '',
        'patient_weight': fields[17] if len(fields) > 17 else '',
        'diagnosis': fields[18] if len(fields) > 18 else '',
        'active_medications': fields[19] if len(fields) > 19 else '',
        'patient_diet': fields[20] if len(fields) > 20 else '',
        'practice_field_1': fields[21] if len(fields) > 21 else '',
        'practice_field_2': fields[22] if len(fields) > 22 else '',
        'admission_discharge_dates': fields[23] if len(fields) > 23 else '',
        'admission_status': fields[24] if len(fields) > 24 else '',
        'location': fields[25] if len(fields) > 25 else '',
        'diagnostic_code_nature_1': fields[26] if len(fields) > 26 else '',
        'diagnostic_code_nature_2': fields[27] if len(fields) > 27 else '',
        'patient_religion': fields[28] if len(fields) > 28 else '',
        'marital_status': fields[29] if len(fields) > 29 else '',
        'isolation_status': fields[30] if len(fields) > 30 else '',
        'language': fields[31] if len(fields) > 31 else '',
        'hospital_service': fields[32] if len(fields) > 32 else '',
        'hospital_institution': fields[33] if len(fields) > 33 else '',
        'dosage_category': fields[34] if len(fields) > 34 else ''
    }
    
    current_session['patients'].append(patient_info)
    logger.info(f"Patient processed: {patient_info['patient_name']} "
                f"(ID: {patient_info['laboratory_patient_id']})")

def process_order_record(record):
    """Process iSED Order record (O)"""
    fields = record.split('|')
    
    # Parse Sample ID field (Sample ID ^ rotor location)
    sample_info = fields[2].split('^') if len(fields) > 2 else []
    
    order_info = {
        'record_type': fields[0] if len(fields) > 0 else '',
        'sequence_number': fields[1] if len(fields) > 1 else '',
        'sample_id': sample_info[0] if len(sample_info) > 0 else '',
        'rotor_location': sample_info[1] if len(sample_info) > 1 else '',
        'instrument_specimen_id': fields[3] if len(fields) > 3 else '',
        'universal_test_id': fields[4] if len(fields) > 4 else '',  # Should be '^^^ESR'
        'priority': fields[5] if len(fields) > 5 else '',
        'requested_datetime': fields[6] if len(fields) > 6 else '',
        'specimen_collection_datetime': fields[7] if len(fields) > 7 else '',
        'collection_end_time': fields[8] if len(fields) > 8 else '',
        'collection_volume': fields[9] if len(fields) > 9 else '',
        'collector_id': fields[10] if len(fields) > 10 else '',
        'action_code': fields[11] if len(fields) > 11 else '',
        'danger_code': fields[12] if len(fields) > 12 else '',
        'clinical_info': fields[13] if len(fields) > 13 else '',
        'specimen_received_datetime': fields[14] if len(fields) > 14 else '',
        'specimen_descriptor': fields[15] if len(fields) > 15 else '',
        'ordering_physician': fields[16] if len(fields) > 16 else '',
        'physician_phone': fields[17] if len(fields) > 17 else '',
        'user_field_1': fields[18] if len(fields) > 18 else '',
        'user_field_2': fields[19] if len(fields) > 19 else '',
        'laboratory_field_1': fields[20] if len(fields) > 20 else '',
        'laboratory_field_2': fields[21] if len(fields) > 21 else '',
        'result_reported_datetime': fields[22] if len(fields) > 22 else '',
        'instrument_charge': fields[23] if len(fields) > 23 else '',
        'instrument_section_id': fields[24] if len(fields) > 24 else '',
        'report_types': fields[25] if len(fields) > 25 else '',  # P: Preliminary result
        'reserved': fields[26] if len(fields) > 26 else '',
        'specimen_location': fields[27] if len(fields) > 27 else '',
        'nosocomial_infection_flag': fields[28] if len(fields) > 28 else '',
        'specimen_service': fields[29] if len(fields) > 29 else '',
        'specimen_institution': fields[30] if len(fields) > 30 else ''
    }
    
    current_session['orders'].append(order_info)
    logger.info(f"Order processed: Sample {order_info['sample_id']} "
                f"(Rotor: {order_info['rotor_location']}, Test: {order_info['universal_test_id']})")

def process_result_record(record):
    """Process iSED Result record (R) - ESR test results"""
    fields = record.split('|')
    
    result_info = {
        'record_type': fields[0] if len(fields) > 0 else '',
        'sequence_number': fields[1] if len(fields) > 1 else '',
        'universal_test_id': fields[2] if len(fields) > 2 else '',  # ^^^ESR^4537-7 (LOINC)
        'result_value': fields[3] if len(fields) > 3 else '',        # ESR result 0-130 or error codes
        'units': fields[4] if len(fields) > 4 else '',               # mm/h
        'reference_range': fields[5] if len(fields) > 5 else '',
        'abnormal_flag': fields[6] if len(fields) > 6 else '',       # '<' or '>' for out of range
        'abnormality_nature': fields[7] if len(fields) > 7 else '',
        'result_status': fields[8] if len(fields) > 8 else '',       # P: Preliminary, X: Cannot do
        'normative_change_date': fields[9] if len(fields) > 9 else '',
        'operator_id': fields[10] if len(fields) > 10 else '',
        'test_start_datetime': fields[11] if len(fields) > 11 else '', # YYYYMMDDHHMMSS
        'test_complete_datetime': fields[12] if len(fields) > 12 else '', # YYYYMMDDHHMMSS
        'instrument_id': fields[13] if len(fields) > 13 else '',      # 01-99
        'timestamp': datetime.now().isoformat()
    }
    
    # Interpret result value
    result_interpretation = interpret_esr_result(result_info['result_value'], 
                                               result_info['abnormal_flag'])
    result_info['interpretation'] = result_interpretation
    
    current_session['results'].append(result_info)
    logger.info(f"Result processed: ESR = {result_info['result_value']} {result_info['units']} "
                f"({result_interpretation}) [Instrument: {result_info['instrument_id']}]")

def interpret_esr_result(result_value, abnormal_flag):
    """Interpret ESR result value and flags"""
    try:
        # Check for error codes (negative values)
        if result_value.startswith('-'):
            error_codes = {
                '-1': 'ESR_ERR_NOFLOW',
                '-2': 'ESR_ERR_NOSPIKE', 
                '-3': 'ESR_ERR_REVERSE',
                '-4': 'ESR_ERR_NOPOINTS',
                '-5': 'ESR_ERR_TOODARK',
                '-7': 'ESR_ERR_TOOCLEAR',
                '-8': 'ESR_ERR_WITHDRAWAL',
                '-9': 'ESR_ERR_FLOW_IN',
                '-10': 'ESR_ERR_FLOW_OUT',
                '-11': 'ESR_ERR_ACQUISITION',
                '-12': 'ESR_ERR_TRIGGERDELAY'
            }
            return error_codes.get(result_value, f'Unknown error code: {result_value}')
        
        # Check for range indicators
        if abnormal_flag == '<':
            return 'Below measurement range (< 1 mm/hr)'
        elif abnormal_flag == '>':
            return 'Above measurement range (> 130 mm/hr)'
        
        # Normal numeric result
        try:
            value = float(result_value)
            return f'Normal measurement: {value} mm/hr'
        except ValueError:
            return f'Invalid result format: {result_value}'
            
    except Exception as e:
        return f'Error interpreting result: {e}'

def process_terminator_record(record):
    """Process iSED Terminator record (L)"""
    fields = record.split('|')
    
    terminator_info = {
        'record_type': fields[0] if len(fields) > 0 else '',
        'sequence_number': fields[1] if len(fields) > 1 else '',  # Should be '1'
        'termination_code': fields[2] if len(fields) > 2 else '', # N: normal
        'timestamp': datetime.now().isoformat()
    }
    
    logger.info(f"Terminator processed: Code '{terminator_info['termination_code']}' "
                f"(Sequence: {terminator_info['sequence_number']})")
    
    # Session complete - save data
    save_session_data()

def save_session_data():
    """Save current iSED session data"""
    try:
        current_session['session_end'] = datetime.now().isoformat()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ised_session_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(current_session, f, indent=2)
            
        # Create summary
        summary = {
            'session_time': current_session['session_end'],
            'instrument': f"{current_session['header'].get('manufacturer', 'N/A')} "
                         f"{current_session['header'].get('product_name', 'N/A')}",
            'software_version': current_session['header'].get('software_version', 'N/A'),
            'instrument_id': current_session['header'].get('instrument_id', 'N/A'),
            'total_patients': len(current_session['patients']),
            'total_orders': len(current_session['orders']),
            'total_results': len(current_session['results']),
            'results_summary': []
        }
        
        # Add result summaries
        for result in current_session['results']:
            summary['results_summary'].append({
                'sample_id': next((o['sample_id'] for o in current_session['orders'] 
                                 if o['sequence_number'] == result['sequence_number']), 'N/A'),
                'result_value': result['result_value'],
                'units': result['units'],
                'interpretation': result['interpretation'],
                'test_complete': result['test_complete_datetime']
            })
        
        logger.info(f"Session data saved to {filename}")
        logger.info(f"Session summary: {summary['total_results']} ESR results from "
                   f"{summary['instrument']} (ID: {summary['instrument_id']})")
        
        # Reset session for next transmission
        current_session.update({
            'header': {},
            'patients': [],
            'orders': [],
            'results': [],
            'session_start': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error saving session data: {e}")

def close_connection():
    """Close serial connection"""
    if ser.is_open:
        ser.close()
        logger.info("Serial connection closed")

# Main execution
if __name__ == "__main__":
    try:
        logger.info("iSED Communication Handler Started")
        logger.info("Waiting for iSED analyzer transmission...")
        process_ised_data()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    finally:
        close_connection()