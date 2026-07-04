require 'xcodeproj'

project_path = 'apps/vitalicast-ios-shell/ios/App/App.xcodeproj'
project = Xcodeproj::Project.open(project_path)

app_target = project.targets.find { |t| t.name == 'App' }
unless app_target
  puts "App target not found"
  exit 1
end

# Check if target already exists
test_target = project.targets.find { |t| t.name == 'VitalicastSecureStorageTests' }
if test_target
  puts "Target already exists"
else
  # Create target
  test_target = project.new_target(:unit_test_bundle, 'VitalicastSecureStorageTests', :ios, '13.0')
  test_target.product_name = 'VitalicastSecureStorageTests'
  
  # Make it app-hosted
  project.root_object.attributes['TargetAttributes'] ||= {}
  project.root_object.attributes['TargetAttributes'][test_target.uuid] = {
    'TestTargetID' => app_target.uuid
  }
  
  # Configure build settings
  test_target.build_configurations.each do |config|
    config.build_settings['TEST_HOST'] = "$(BUILT_PRODUCTS_DIR)/App.app/App"
    config.build_settings['BUNDLE_LOADER'] = "$(TEST_HOST)"
    config.build_settings['INFOPLIST_FILE'] = "VitalicastSecureStorageTests/Info.plist" # Might not exist, but let's see. XCTest defaults
    config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = "com.hutchstack.vitalicast.VitalicastSecureStorageTests"
    config.build_settings['SWIFT_VERSION'] = "5.0"
  end

  group = project.main_group.find_subpath('VitalicastSecureStorageTests', true)
  # Actually, the file is in apps/vitalicast-ios-shell/ios/App/VitalicastSecureStorageTests/VitalicastSecureStorageTests.swift
  # Set the group path to VitalicastSecureStorageTests
  group.set_source_tree('<group>')
  group.set_path('VitalicastSecureStorageTests')
  
  file_ref = group.new_file('VitalicastSecureStorageTests.swift')
  test_target.add_file_references([file_ref])
end

# Save project
project.save

puts "UUID: #{test_target.uuid}"

# Update scheme
scheme_path = File.join(project_path, 'xcshareddata', 'xcschemes', 'App.xcscheme')
scheme = Xcodeproj::XCScheme.new(scheme_path)

# check if it already has this target in test action
test_action = scheme.test_action
unless test_action
  test_action = Xcodeproj::XCScheme::TestAction.new
  scheme.test_action = test_action
end

testables = test_action.testables
already_added = testables.any? { |t| t.buildable_references.any? { |ref| ref.blueprint_identifier == test_target.uuid } }

unless already_added
  testable = Xcodeproj::XCScheme::TestAction::TestableReference.new(test_target)
  test_action.add_testable(testable)
  scheme.save!
  puts "Added testable to scheme"
else
  puts "Testable already in scheme"
end
