require 'xcodeproj'

project_path = 'apps/vitalicast-ios-shell/ios/App/App.xcodeproj'
project = Xcodeproj::Project.open(project_path)

app_target = project.targets.find { |t| t.name == 'App' }

test_target = project.targets.find { |t| t.name == 'VitalicastSecureStorageTests' }
if test_target
  puts "Target already exists"
else
  test_target = project.new_target(:unit_test_bundle, 'VitalicastSecureStorageTests', :ios, '13.0')
  test_target.product_name = 'VitalicastSecureStorageTests'
  
  project.root_object.attributes['TargetAttributes'] ||= {}
  project.root_object.attributes['TargetAttributes'][test_target.uuid] = {
    'TestTargetID' => app_target.uuid
  }
  
  test_target.build_configurations.each do |config|
    config.build_settings['TEST_HOST'] = "$(BUILT_PRODUCTS_DIR)/App.app/App"
    config.build_settings['BUNDLE_LOADER'] = "$(TEST_HOST)"
    config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = "com.hutchstack.vitalicast.VitalicastSecureStorageTests"
    config.build_settings['SWIFT_VERSION'] = "5.0"
  end

  group = project.main_group.find_subpath('VitalicastSecureStorageTests', true)
  group.set_source_tree('<group>')
  group.set_path('VitalicastSecureStorageTests')
  
  file_ref = group.new_file('VitalicastSecureStorageTests.swift')
  test_target.add_file_references([file_ref])
end

project.save
puts "APP_UUID: #{app_target.uuid}"
puts "TEST_UUID: #{test_target.uuid}"
