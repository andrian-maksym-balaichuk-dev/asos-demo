"""Demo B (záloha z terminálu): SOAP/WSDL a gRPC deadline.

gRPC volanie robí API kontajner (→ grpc:50051); skript volá iba HTTP endpointy /demo/rpc/*.

Spustenie:
    python3 scripts/demo_rpc.py --show-wsdl --check-seat A7
    python3 scripts/demo_rpc.py --soap-fault
    python3 scripts/demo_rpc.py --grpc-delay-ms 800 --deadline-ms 200
"""
import argparse
import re

from _client import get, line, title


def show_wsdl():
    title("SOAP: GET /soap?wsdl (výrez)")
    wsdl = get("/soap?wsdl").body
    for wsdl_line in wsdl.splitlines():
        if "CheckSeat" in wsdl_line or "soap:address" in wsdl_line:
            print("  " + wsdl_line.strip())


def check_seat(seat):
    # 1. SOAP: celé XML + veľkosť HTTP body
    title(f"SOAP: CheckSeat(42, {seat})")
    soap = get(f"/demo/rpc/soap?seat={seat}").json
    print(soap["request_xml"])
    print(f"  HTTP {soap['http_status']} · request {soap['request_body_bytes']} B · "
          f"response {soap['response_body_bytes']} B (HTTP body)")
    print(soap["response_xml"])

    # 2. gRPC: rovnaká otázka, binárny protobuf
    title(f"gRPC: CheckSeat(42, {seat})")
    grpc = get(f"/demo/rpc/grpc?seat={seat}").json
    print(f"  {grpc['code']} · reply={grpc.get('reply')} · {grpc['client_elapsed_ms']} ms")
    print(f"  protobuf: request {grpc['request_protobuf_bytes']} B · response {grpc.get('response_protobuf_bytes')} B "
          "(bez HTTP/2 rámcov a hlavičiek)")


def soap_fault():
    title("SOAP: neplatný request (chýba seatId)")
    soap = get("/demo/rpc/soap?invalid=true").json
    print(f"  HTTP {soap['http_status']} · fault={soap['is_fault']}")
    faultstring = re.search(r"<faultstring>(.*?)</faultstring>", soap["response_xml"])
    print("  " + (faultstring[1] if faultstring else "?"))


def grpc_deadline(delay_ms, deadline_ms):
    deadline_param = f"&deadline_ms={deadline_ms}" if deadline_ms else ""
    title(f"gRPC: server delay {delay_ms} ms, deadline {deadline_ms or '—'} ms")
    grpc = get(f"/demo/rpc/grpc?seat=A7&delay_ms={delay_ms}{deadline_param}").json
    print(f"  stav: {grpc['code']} · {grpc.get('details') or grpc.get('reply')}")
    print(f"  klient skončil po {grpc['client_elapsed_ms']} ms "
          f"(deadline {deadline_ms} ms, server chcel pracovať {delay_ms} ms)")
    # Klient prestane čakať pri deadline, aj keď server by ešte pracoval
    if deadline_ms and delay_ms > deadline_ms:
        line(grpc["code"] == "DEADLINE_EXCEEDED", "DEADLINE_EXCEEDED — čas a timeout sú odlišné pojmy")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-wsdl", action="store_true")
    parser.add_argument("--check-seat", metavar="SEAT")
    parser.add_argument("--soap-fault", action="store_true", help="pošli neplatný SOAP request")
    parser.add_argument("--grpc-delay-ms", type=int)
    parser.add_argument("--deadline-ms", type=int)
    args = parser.parse_args()

    if args.show_wsdl:
        show_wsdl()
    if args.check_seat:
        check_seat(args.check_seat)
    if args.soap_fault:
        soap_fault()
    if args.grpc_delay_ms is not None:
        grpc_deadline(args.grpc_delay_ms, args.deadline_ms)
    if not any([args.show_wsdl, args.check_seat, args.soap_fault, args.grpc_delay_ms is not None]):
        parser.print_help()


if __name__ == "__main__":
    main()
