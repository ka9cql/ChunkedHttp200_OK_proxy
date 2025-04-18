import socket
import select
import time
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from http.client import HTTPConnection, HTTPSConnection
import urllib.parse
import ssl
import re
import uuid

class KeepAliveProxy(BaseHTTPRequestHandler):
    # class variables
    active_keepalive_threads = {}
    keepalive_lock = threading.Lock()

    # Configuration
    BUFFER_SIZE = 8192
    KEEPALIVE_INTERVAL = 30  # seconds between keepalive chunks
    CHUNK_SIZE = 1  # size of keepalive chunk
    TARGET_HOST = "localhost"  # Default target, can be changed
    TARGET_PORT = 8000  # Default port, can be changed
    SEND_EARLY_RESPONSE = True  # Send 200 OK before server responds

    def do_METHOD(self):
        """Handle any HTTP method by forwarding it to the target server"""
        request_method = self.command

        # Parse the request URL
        parsed_path = urllib.parse.urlparse(self.path)
        target_host = self.TARGET_HOST
        target_port = self.TARGET_PORT
        
        # If the proxy is used with a full URL, extract the host and port
        if parsed_path.netloc:
            target_host = parsed_path.netloc
            target_path = parsed_path.path
            if parsed_path.query:
                target_path += '?' + parsed_path.query
            
            # Handle port if specified in the URL
            if ':' in target_host:
                target_host, port = target_host.split(':')
                target_port = int(port)
        else:
            target_path = self.path
        
        # Check if this is HTTPS
        is_https = parsed_path.scheme == 'https'
        
        print(f"Proxying {request_method} request to {target_host}:{target_port}{target_path}")
        sys.stdout.flush()
        
        # Read request body if present
        content_length = int(self.headers.get('Content-Length', 0))
        request_body = self.rfile.read(content_length) if content_length > 0 else None
        
        # Generate a request ID for tracking
        request_id = str(uuid.uuid4())
        
        # Create an event for signaling thread termination
        stop_event = threading.Event()

        # If configured to send early response, do it now before contacting the server
        if self.SEND_EARLY_RESPONSE:
            print(f"Sending early 200 OK response for request {request_id}")
            sys.stdout.flush()
            
            # Send immediate 200 OK response
            self.send_response(200)
            self.send_header('X-Request-ID', request_id)
            self.send_header('Connection', 'keep-alive')
            self.send_header('Transfer-Encoding', 'chunked')
            #self.send_header('Keep-Alive', 'timeout=60, max=500')
            # self.send_header('X-Early-Response', 'true')
            self.end_headers()
            
            # Send an initial chunk with some information
            #initial_message = ""
            #self.wfile.write(f"{len(initial_message):x}\r\n".encode())
            #self.wfile.write(initial_message.encode())
            #self.wfile.write(b"\r\n")
            #self.wfile.flush()

            # Start keepalive thread with stop_event
            with self.keepalive_lock:
                keepalive_thread = threading.Thread(
                    target=self.send_keepalive_chunks,
                    args=(None, request_id, stop_event)
                )
                keepalive_thread.daemon = True
                self.active_keepalive_threads[request_id] = (keepalive_thread, stop_event)
                keepalive_thread.start()
            
        # Forward the request to the target server
        try:
            # Create connection to target
            if is_https:
                conn = HTTPSConnection(target_host, target_port, context=ssl._create_unverified_context())
            else:
                conn = HTTPConnection(target_host, target_port)
            
            # Copy request headers
            headers = {}
            for header, value in self.headers.items():
                # Skip hop-by-hop headers
                if header.lower() not in ['connection', 'keep-alive', 'proxy-connection', 'transfer-encoding']:
                    headers[header] = value
            
            # Add request ID to headers
            headers['X-Request-ID'] = request_id
            
            # Send the request to the target server
            conn.request(request_method, target_path, body=request_body, headers=headers)
            response = conn.getresponse()
            
            print(f"Received response from target for request {request_id}: {response.status} {response.reason}")
            sys.stdout.flush()
            
            # If we haven't sent an early response, send the actual response now
            if not self.SEND_EARLY_RESPONSE:
                self.send_response(response.status)
                self.send_header('X-Request-ID', request_id)
                self.send_header('Connection', 'keep-alive')
                self.send_header('Transfer-Encoding', 'chunked')
                #self.send_header('Keep-Alive', 'timeout=60, max=500')
                
                # Copy response headers from target
                for header, value in response.getheaders():
                    if header.lower() not in ['connection', 'transfer-encoding', 'keep-alive', 'content-length']:
                        self.send_header(header, value)
                
                self.end_headers()

                # Start keepalive thread with stop_event
                with self.keepalive_lock:
                    keepalive_thread = threading.Thread(
                        target=self.send_keepalive_chunks,
                        args=(None, request_id, stop_event)
                    )
                    keepalive_thread.daemon = True
                    self.active_keepalive_threads[request_id] = (keepalive_thread, stop_event)
                    keepalive_thread.start()

            # For early response mode, send server response headers in a chunk
            # if self.SEND_EARLY_RESPONSE:
            if False:
                # Create a chunk with server response info
                headers_info = f"Server responded with: {response.status} {response.reason}\n"
                header_list = []
                for header, value in response.getheaders():
                    if header.lower() not in ['connection', 'transfer-encoding', 'content-length']:
                        header_list.append(f"{header}: {value}")
                
                if header_list:
                    headers_info += "Response headers:\n" + "\n".join(header_list) + "\n\n"
                
                # Send this info as a chunk
                self.wfile.write(f"{len(headers_info):x}\r\n".encode())
                self.wfile.write(headers_info.encode())
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            
            print(f"Starting to stream response for request {request_id} to client...")
            sys.stdout.flush()
            
            # Forward response body to client using chunked encoding
            total_bytes = 0
            chunk_count = 0
            while True:
                chunk = response.read(self.BUFFER_SIZE)
                if not chunk:
                    break
                
                total_bytes += len(chunk)
                chunk_count += 1
                
                # Send chunk using chunked transfer encoding format
                self.wfile.write(f"{len(chunk):x}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                
                if chunk_count % 10 == 0:
                    print(f"Request {request_id}: Sent {chunk_count} chunks, {total_bytes} bytes so far")
                    sys.stdout.flush()
            
            ### MOVE TO LAST-KEEPALIVE SECTION?
            # End chunked response
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            
            print(f"Completed request {request_id}, sent {total_bytes} bytes to client")
            sys.stdout.flush()

            ## BAD - # Close connection toward client
            ## self.wfile.close()

        except Exception as e:
            print(f"Error handling request {request_id}: {e}")
            sys.stdout.flush()
            
            # If we already sent an early 200 OK, send error info in a chunk
            if self.SEND_EARLY_RESPONSE:
                try:
                    error_message = f"Error communicating with server: {str(e)}\n"
                    self.wfile.write(f"{len(error_message):x}\r\n".encode())
                    self.wfile.write(error_message.encode())
                    self.wfile.write(b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")  # End chunked response
                    self.wfile.flush()
                except:
                    pass  # Client might have disconnected
            else:
                # Otherwise send error response
                try:
                    self.send_error(502, f"Bad Gateway: {str(e)}")
                except:
                    pass  # Client might have disconnected

        # Stop the thread if it's still running
        self.stop_keepalive_thread(request_id)
    
    def send_keepalive_chunks(self, response, request_id, stop_event):
        """Send empty keepalive chunks to keep client connection alive"""
        count = 0
        try:
            #while count < 500 and not stop_event.is_set():       # TO-DO: MATCH THIS TO **BOTH** max=xx NUMBERS!
            while count < 20 and not stop_event.is_set():       # TO-DO: MATCH THIS TO **BOTH** max=xx NUMBERS!
                # Check if the main response is still being processed
                if response and (not hasattr(response, 'will_close') or response.will_close):
                    break

                # Wait with timeout, checking for stop_event
                # This allows the thread to exit quickly when requested
                if stop_event.wait(timeout=self.KEEPALIVE_INTERVAL):
                    print(f"Request {request_id}: Keepalive thread received stop signal")
                    sys.stdout.flush()
                    break

                count += 1

                # Write a comment chunk according to chunked transfer encoding
                try:
                    # Using an HTML comment format with special markers
                    # This won't be interpreted as valid JSON by parsers
                    ### keepalive_msg = f"<!-- KEEPALIVE_CHUNK_{count}_{request_id} -->\n"
                    keepalive_msg = f" "
                    self.wfile.write(f"{len(keepalive_msg):x}\r\n".encode())
                    self.wfile.write(keepalive_msg.encode())
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

                    print(f"Request {request_id}: Sent keepalive chunk #{count}")
                    sys.stdout.flush()
                except:
                    # Client disconnected
                    print(f"Request {request_id}: Client disconnected, stopping keepalive")
                    sys.stdout.flush()
                    break

        except Exception as e:
            # Thread cleanup
            print(f"Request {request_id}: Keepalive thread ended: {e}")
            sys.stdout.flush()
        finally:
            # Remove thread from active threads dictionary
            with self.keepalive_lock:
                if request_id in self.active_keepalive_threads:
                    del self.active_keepalive_threads[request_id]

    def stop_keepalive_thread(self, request_id):
        """Stop a keepalive thread by its request ID"""
        with self.keepalive_lock:
            if request_id in self.active_keepalive_threads:
                _, stop_event = self.active_keepalive_threads[request_id]
                stop_event.set()
                print(f"Request {request_id}: Signaled keepalive thread to stop")
                sys.stdout.flush()
    
    @classmethod
    def stop_all_keepalive_threads(cls):
        """Stop all active keepalive threads"""
        with cls.keepalive_lock:
            for request_id, (_, stop_event) in cls.active_keepalive_threads.items():
                stop_event.set()
                print(f"Request {request_id}: Signaled keepalive thread to stop during shutdown")
                sys.stdout.flush()
            cls.active_keepalive_threads.clear()

    
    # Handle all HTTP methods
    def do_GET(self): self.do_METHOD()
    def do_POST(self): self.do_METHOD()
    def do_PUT(self): self.do_METHOD()
    def do_DELETE(self): self.do_METHOD()
    def do_HEAD(self): self.do_METHOD()
    def do_OPTIONS(self): self.do_METHOD()
    def do_PATCH(self): self.do_METHOD()
    
    def do_CONNECT(self):
        """Handle CONNECT tunneling for HTTPS"""
        try:
            # Parse target address
            host_port = self.path.split(':')
            host = host_port[0]
            port = int(host_port[1]) if len(host_port) > 1 else 443
            
            print(f"CONNECT tunnel request to {host}:{port}")
            sys.stdout.flush()
            
            # Connect to remote server
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.connect((host, port))
            
            # Respond to client that tunnel is ready
            self.send_response(200, 'Connection established')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            print(f"Tunnel established to {host}:{port}")
            sys.stdout.flush()
            
            # Start bidirectional tunnel
            self.tunnel_connection(server_socket)
            
        except Exception as e:
            print(f"CONNECT error: {e}")
            sys.stdout.flush()
            try:
                self.send_error(502, f"Bad Gateway: {str(e)}")
            except:
                pass
    
    def tunnel_connection(self, server_socket):
        """Create a bidirectional tunnel between client and server"""
        client_socket = self.connection
        client_addr = self.client_address
        
        print(f"Starting tunnel for client {client_addr}")
        sys.stdout.flush()
        
        # Create two-way pipe
        sockets = [client_socket, server_socket]
        keep_tunneling = True
        
        bytes_to_server = 0
        bytes_to_client = 0
        
        while keep_tunneling:
            # Use select to wait for available data
            readable, _, exceptional = select.select(sockets, [], sockets, 10)
            
            if exceptional:
                print("Exceptional condition on socket, closing tunnel")
                sys.stdout.flush()
                break
                
            for sock in readable:
                other = server_socket if sock is client_socket else client_socket
                direction = "to server" if sock is client_socket else "to client"
                try:
                    data = sock.recv(self.BUFFER_SIZE)
                    if not data:
                        print(f"No more data {direction}, closing tunnel")
                        sys.stdout.flush()
                        keep_tunneling = False
                        break
                    
                    if sock is client_socket:
                        bytes_to_server += len(data)
                    else:
                        bytes_to_client += len(data)
                        
                    other.sendall(data)
                except Exception as e:
                    print(f"Error in tunnel {direction}: {e}")
                    sys.stdout.flush()
                    keep_tunneling = False
                    break
        
        # Clean up
        server_socket.close()
        print(f"Tunnel closed. Bytes to server: {bytes_to_server}, Bytes to client: {bytes_to_client}")
        sys.stdout.flush()

def run_proxy(host='0.0.0.0', port=8080, target_host=None, target_port=None, early_response=True):
    """Run the proxy server"""
    if target_host:
        KeepAliveProxy.TARGET_HOST = target_host
    if target_port:
        KeepAliveProxy.TARGET_PORT = target_port
    
    KeepAliveProxy.SEND_EARLY_RESPONSE = early_response
    
    server_address = (host, port)
    httpd = HTTPServer(server_address, KeepAliveProxy)
    print(f"Starting HTTP proxy server on {host}:{port}")
    print(f"Default target: {KeepAliveProxy.TARGET_HOST}:{KeepAliveProxy.TARGET_PORT}")
    print(f"Early response mode: {'Enabled' if KeepAliveProxy.SEND_EARLY_RESPONSE else 'Disabled'}")
    sys.stdout.flush()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down proxy server")
        sys.stdout.flush()
        # Stop all keepalive threads before shutting down
        KeepAliveProxy.stop_all_keepalive_threads()
        httpd.server_close()






if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='HTTP proxy server with keepalive support')
    parser.add_argument('--host', default='0.0.0.0', help='Proxy server host (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8080, help='Proxy server port (default: 8080)')
    parser.add_argument('--target-host', help='Default target host (default: localhost)')
    parser.add_argument('--target-port', type=int, help='Default target port (default: 8000)')
    parser.add_argument('--no-early-response', action='store_false', dest='early_response', 
                        help='Disable sending 200 OK before server response')
    
    args = parser.parse_args()
    
    run_proxy(args.host, args.port, args.target_host, args.target_port, args.early_response)
