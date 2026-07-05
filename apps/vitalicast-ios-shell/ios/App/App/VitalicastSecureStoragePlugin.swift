import Foundation
import Capacitor
import Security

@objc(VitalicastSecureStoragePlugin)
public class VitalicastSecureStoragePlugin: CAPPlugin {
    
    private static let archiveService = "com.vitalicast.archive"
    
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
        
        // FIRST: canonical exact-service read
        let canonicalQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: storageKey,
            kSecAttrService as String: Self.archiveService,
            kSecReturnData as String: kCFBooleanTrue!,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        var canonicalDataTypeRef: AnyObject?
        let canonicalStatus = SecItemCopyMatching(canonicalQuery as CFDictionary, &canonicalDataTypeRef)
        
        if canonicalStatus == errSecSuccess, let data = canonicalDataTypeRef as? Data, let value = String(data: data, encoding: .utf8) {
            call.resolve(["value": value])
            return
        } else if canonicalStatus != errSecItemNotFound {
            call.reject("Failed to read secure record, OSStatus: \(canonicalStatus)")
            return
        }
        
        // SECOND: legacy exact compatibility read
        let legacyQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: storageKey,
            kSecReturnData as String: kCFBooleanTrue!,
            kSecReturnAttributes as String: kCFBooleanTrue!,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        var legacyDataTypeRef: AnyObject?
        let legacyStatus = SecItemCopyMatching(legacyQuery as CFDictionary, &legacyDataTypeRef)
        
        if legacyStatus == errSecSuccess {
            guard let resultDict = legacyDataTypeRef as? [String: Any],
                  let payloadData = resultDict[kSecValueData as String] as? Data,
                  let value = String(data: payloadData, encoding: .utf8) else {
                call.reject("Failed to parse legacy fallback result")
                return
            }
            
            if !isOmittedServiceIdentity(resultDict[kSecAttrService as String]) {
                call.resolve(["value": NSNull()])
                return
            }
            
            call.resolve(["value": value])
        } else if legacyStatus == errSecItemNotFound {
            call.resolve(["value": NSNull()])
        } else {
            call.reject("Failed to read secure record, OSStatus: \(legacyStatus)")
        }
    }
    
    private func isOmittedServiceIdentity(_ service: Any?) -> Bool {
        guard let serviceString = service as? String else {
            return true
        }
        return serviceString.isEmpty
    }
    
    @objc func listArchiveStorageKeys(_ call: CAPPluginCall) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.archiveService,
            kSecReturnData as String: kCFBooleanFalse!,
            kSecReturnAttributes as String: kCFBooleanTrue!,
            kSecMatchLimit as String: kSecMatchLimitAll
        ]
        
        var dataTypeRef: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &dataTypeRef)
        
        if status == errSecItemNotFound {
            call.resolve(["keys": []])
            return
        } else if status != errSecSuccess {
            call.reject("Failed to list archive keys, OSStatus: \(status)")
            return
        }
        
        var validAccounts = Set<String>()
        
        if let items = dataTypeRef as? [[String: Any]] {
            for item in items {
                if let account = item[kSecAttrAccount as String] as? String {
                    if account.hasPrefix("vitalicast_canonical_") || account.hasPrefix("vitalicast_addendum_") {
                        validAccounts.insert(account)
                    }
                }
            }
        } else if let item = dataTypeRef as? [String: Any] {
            if let account = item[kSecAttrAccount as String] as? String {
                if account.hasPrefix("vitalicast_canonical_") || account.hasPrefix("vitalicast_addendum_") {
                    validAccounts.insert(account)
                }
            }
        }
        
        let sortedKeys = validAccounts.sorted()
        call.resolve(["keys": sortedKeys])
    }
    
    private func addKeychainItem(key: String, value: String) -> OSStatus {
        guard let data = value.data(using: .utf8) else {
            return errSecParam
        }
        
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecAttrService as String: Self.archiveService,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        
        return SecItemAdd(query as CFDictionary, nil)
    }
}
