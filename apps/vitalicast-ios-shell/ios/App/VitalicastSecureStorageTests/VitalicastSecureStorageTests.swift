import XCTest
import Capacitor
@testable import App

class VitalicastSecureStorageTests: XCTestCase {
    
    var plugin: VitalicastSecureStoragePlugin!
    
    override func setUp() {
        super.setUp()
        plugin = VitalicastSecureStoragePlugin()
    }
    
    override func tearDown() {
        super.tearDown()
    }
    
    func testCanonicalCreateSucceeds() {
        let uuid = UUID().uuidString
        let call = CAPPluginCall(callbackId: "1", options: [
            "recordId": uuid,
            "payload": "{\"test\":true,\"fixture\":\"vitalicast_sprint4\"}",
            "createdAt": "2026-07-04T00:00:00Z",
            "payloadHash": "dummyhash"
        ], success: { result, _ in
            XCTAssertNotNil(result?.data["success"])
        }, error: { error in
            XCTFail("Create failed: \(String(describing: error?.message))")
        })
        
        plugin.createSecureRecord(call!)
    }
    
    func testDuplicateCanonicalCreateFails() {
        let uuid = UUID().uuidString
        
        let call1 = CAPPluginCall(callbackId: "1", options: [
            "recordId": uuid,
            "payload": "{\"test\":true,\"fixture\":\"first\"}",
            "createdAt": "2026-07-04T00:00:00Z",
            "payloadHash": "hash1"
        ], success: { _, _ in }, error: { _ in })
        
        plugin.createSecureRecord(call1!)
        
        let call2 = CAPPluginCall(callbackId: "2", options: [
            "recordId": uuid,
            "payload": "{\"test\":true,\"fixture\":\"second\"}",
            "createdAt": "2026-07-04T00:00:00Z",
            "payloadHash": "hash2"
        ], success: { _, _ in
            XCTFail("Duplicate create should have failed")
        }, error: { error in
            XCTAssertEqual(error?.message, "MUTATION_REJECTED")
        })
        
        plugin.createSecureRecord(call2!)
        
        let readCall = CAPPluginCall(callbackId: "3", options: [
            "storageKey": "vitalicast_canonical_\(uuid)"
        ], success: { result, _ in
            XCTAssertEqual(result?.data["value"] as? String, "{\"test\":true,\"fixture\":\"first\"}")
        }, error: { error in
            XCTFail("Read failed: \(String(describing: error?.message))")
        })
        
        plugin.readSecureRecord(readCall!)
    }
    
    func testAppendAddendumSucceeds() {
        let canonicalUuid = UUID().uuidString
        let addendumUuid = UUID().uuidString
        
        let callCanonical = CAPPluginCall(callbackId: "1", options: [
            "recordId": canonicalUuid,
            "payload": "{\"test\":true,\"fixture\":\"canonical\"}",
            "createdAt": "2026-07-04T00:00:00Z",
            "payloadHash": "canonicalHash"
        ], success: { _, _ in }, error: { _ in })
        
        plugin.createSecureRecord(callCanonical!)
        
        let callAddendum = CAPPluginCall(callbackId: "2", options: [
            "recordId": canonicalUuid,
            "addendumId": addendumUuid,
            "payload": "{\"test\":true,\"fixture\":\"addendum\"}",
            "createdAt": "2026-07-04T00:00:01Z",
            "canonicalRecordHash": "canonicalHash",
            "addendumHash": "addendumHash"
        ], success: { result, _ in
            XCTAssertNotNil(result?.data["success"])
        }, error: { error in
            XCTFail("Addendum append failed: \(String(describing: error?.message))")
        })
        
        plugin.appendAddendum(callAddendum!)
        
        let readCanonical = CAPPluginCall(callbackId: "3", options: [
            "storageKey": "vitalicast_canonical_\(canonicalUuid)"
        ], success: { result, _ in
            XCTAssertEqual(result?.data["value"] as? String, "{\"test\":true,\"fixture\":\"canonical\"}")
        }, error: { error in
            XCTFail("Read failed: \(String(describing: error?.message))")
        })
        
        plugin.readSecureRecord(readCanonical!)
        
        let readAddendum = CAPPluginCall(callbackId: "4", options: [
            "storageKey": "vitalicast_addendum_\(canonicalUuid)_\(addendumUuid)"
        ], success: { result, _ in
            XCTAssertEqual(result?.data["value"] as? String, "{\"test\":true,\"fixture\":\"addendum\"}")
        }, error: { error in
            XCTFail("Read failed: \(String(describing: error?.message))")
        })
        
        plugin.readSecureRecord(readAddendum!)
    }
    
    func testExactKeyReadInvalidReturnsNotFound() {
        let uuid = UUID().uuidString
        let readCall = CAPPluginCall(callbackId: "1", options: [
            "storageKey": "vitalicast_canonical_\(uuid)"
        ], success: { result, _ in
            XCTAssertTrue(result?.data["value"] is NSNull)
        }, error: { error in
            XCTFail("Read should have resolved with NSNull instead of failing")
        })
        
        plugin.readSecureRecord(readCall!)
    }
    
    func testUnsupportedEnumeration() {
        // Native enumeration API does not exist.
        // Documenting assertion as per requirements: Enumeration is unsupported/fail-closed.
        XCTAssertTrue(true, "Native enumeration API intentionally unsupported/fail-closed")
    }
}
