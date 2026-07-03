import Foundation
import Capacitor
import Security

@objc(VitalicastSecureStoragePlugin)
public class VitalicastSecureStoragePlugin: CAPPlugin {
    
    @objc func isAvailable(_ call: CAPPluginCall) {
        call.resolve(["available": true])
    }
    
    @objc func createSecureRecord(_ call: CAPPluginCall) {
        guard let recordId = call.getString("recordId"),
              let payload = call.getString("payload"),
              let createdAt = call.getString("createdAt"),
              let payloadHash = call.getString("payloadHash") else {
            call.reject("Missing required fields (recordId, payload, createdAt, payloadHash)")
            return
        }
        
        let storageKey = "vitalicast_canonical_\(recordId)"
        
        // No SecItemUpdate is permitted. Use SecItemAdd for create-only.
        let status = addKeychainItem(key: storageKey, value: payload)
        
        if status == errSecDuplicateItem {
            call.reject("MUTATION_REJECTED")
        } else if status != errSecSuccess {
            call.reject("Failed to create secure record, OSStatus: \(status)")
        } else {
            call.resolve(["success": true])
        }
    }
    
    @objc func appendAddendum(_ call: CAPPluginCall) {
        guard let recordId = call.getString("recordId"),
              let addendumId = call.getString("addendumId"),
              let payload = call.getString("payload"),
              let createdAt = call.getString("createdAt"),
              let canonicalRecordHash = call.getString("canonicalRecordHash"),
              let addendumHash = call.getString("addendumHash") else {
            call.reject("Missing required fields for addendum")
            return
        }
        
        let storageKey = "vitalicast_addendum_\(recordId)_\(addendumId)"
        
        let status = addKeychainItem(key: storageKey, value: payload)
        
        if status == errSecDuplicateItem {
            call.reject("MUTATION_REJECTED")
        } else if status != errSecSuccess {
            call.reject("Failed to append addendum, OSStatus: \(status)")
        } else {
            call.resolve(["success": true])
        }
    }
    
    @objc func readSecureRecord(_ call: CAPPluginCall) {
        guard let storageKey = call.getString("storageKey") else {
            call.reject("Missing storageKey")
            return
        }
        
        if !storageKey.hasPrefix("vitalicast_canonical_") && !storageKey.hasPrefix("vitalicast_addendum_") {
            call.reject("Invalid storageKey prefix")
            return
        }
        
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: storageKey,
            kSecReturnData as String: kCFBooleanTrue!,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        var dataTypeRef: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &dataTypeRef)
        
        if status == errSecSuccess, let data = dataTypeRef as? Data, let value = String(data: data, encoding: .utf8) {
            call.resolve(["value": value])
        } else if status == errSecItemNotFound {
            call.resolve(["value": NSNull()])
        } else {
            call.reject("Failed to read secure record, OSStatus: \(status)")
        }
    }
    
    private func addKeychainItem(key: String, value: String) -> OSStatus {
        guard let data = value.data(using: .utf8) else {
            return errSecParam
        }
        
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        
        return SecItemAdd(query as CFDictionary, nil)
    }
}
