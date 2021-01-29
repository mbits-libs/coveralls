option(${COVERALLS_PREFIX}COVERALLS "Turn on coveralls support" OFF)
option(${COVERALLS_PREFIX}COVERALLS_EXTERNAL_TESTS "Create an empty coveralls_test" OFF)
option(${COVERALLS_PREFIX}COVERALLS_UPLOAD "Upload the generated coveralls json" OFF)

if (${COVERALLS_PREFIX}COVERALLS)
	if (NOT MSVC)
		set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fprofile-arcs -ftest-coverage")
		set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fprofile-arcs -ftest-coverage")
		set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} --coverage -lgcov")
		set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} --coverage -lgcov")
	endif()
	if (NOT DEFINED ${COVERALLS_PREFIX}COVERALLS_FILE)
		set(${COVERALLS_PREFIX}COVERALLS_FILE ${PROJECT_BINARY_DIR}/coveralls.json)
	endif()

	if (NOT ${COVERALLS_PREFIX}COVERALLS_DIRS)
		message(FATAL_ERROR "${COVERALLS_PREFIX}COVERALLS_DIRS not set. Aborting")
	endif()

	string(REPLACE "." ";" ${COVERALLS_PREFIX}COVERALLS_CXX_VER ${CMAKE_CXX_COMPILER_VERSION})
	list(GET ${COVERALLS_PREFIX}COVERALLS_CXX_VER 0 ${COVERALLS_PREFIX}COVERALLS_CXX_VER_MAJOR)
	list(GET ${COVERALLS_PREFIX}COVERALLS_CXX_VER 1 ${COVERALLS_PREFIX}COVERALLS_CXX_VER_MINOR)

	if (WIN32)
		find_program(OCC_EXECUTABLE NAMES OpenCppCoverage HINTS "C:/Program Files/OpenCppCoverage")
		message(STATUS "OCC_EXECUTABLE is: ${OCC_EXECUTABLE}")
	else()
		find_program(GCOV_EXECUTABLE NAMES gcov-${${COVERALLS_PREFIX}COVERALLS_CXX_VER_MAJOR}.${${COVERALLS_PREFIX}COVERALLS_CXX_VER_MINOR} gcov-${${COVERALLS_PREFIX}COVERALLS_CXX_VER_MAJOR} gcov)
		if (NOT GCOV_EXECUTABLE)
			message(FATAL_ERROR "gcov not found! Aborting...")
		endif()
	endif()

	find_package(Git)

	if (UNIX)
		add_custom_target(coveralls_clean_counters
			# Reset all counters
			COMMAND find -name '*.gcda' -exec rm {} '\;'
			WORKING_DIRECTORY "${PROJECT_BINARY_DIR}"
			COMMENT "Removing GCDA counters..."
		)
		add_custom_target(coveralls_remove_intermediate_files
			COMMAND rm -rf gcov
			COMMAND mkdir -p gcov
			WORKING_DIRECTORY "${PROJECT_BINARY_DIR}"
			COMMENT "Preparing for gcov..."
		)
		add_custom_target(coveralls_prepare
			DEPENDS
				coveralls_clean_counters
				coveralls_remove_intermediate_files
			)
		set_target_properties(coveralls_clean_counters coveralls_remove_intermediate_files coveralls_prepare PROPERTIES FOLDER "Coveralls Targets")
	else()
		add_custom_target(coveralls_prepare)
		set_target_properties(coveralls_prepare PROPERTIES FOLDER "Coveralls Targets")
	endif()

	if (${COVERALLS_PREFIX}COVERALLS_EXTERNAL_TESTS)
		message(STATUS "COVERALLS_EXTERNAL_TESTS")
		add_custom_target(coveralls_test
			DEPENDS coveralls_prepare
		)
	elseif(OCC_EXECUTABLE)
		if (NOT ${COVERALLS_PREFIX}COVERALLS_CONFIGURATION)
			set(${COVERALLS_PREFIX}COVERALLS_CONFIGURATION "Debug")
		endif()
		string(REPLACE "/" "\\" DOS_CMAKE_CTEST_COMMAND "${CMAKE_CTEST_COMMAND}")
		string(REPLACE "/" "\\" DOS_PROJECT_BINARY_DIR "${PROJECT_BINARY_DIR}")

		set(OCC_SOURCES)
		foreach(DIR_NAME ${${COVERALLS_PREFIX}COVERALLS_DIRS})
			get_filename_component(ABSNAME "${DIR_NAME}" ABSOLUTE BASE_DIR "${PROJECT_SOURCE_DIR}")
			string(REPLACE "/" "\\" DOS_ABSNAME "${ABSNAME}")
			list(APPEND OCC_SOURCES --source "${DOS_ABSNAME}")
		endforeach()
	

		add_custom_target(coveralls_test
			# Run tests and regenerate the counters
			COMMAND "${OCC_EXECUTABLE}" -q
				--working_dir "${DOS_PROJECT_BINARY_DIR}"
				--export_type "cobertura:${DOS_PROJECT_BINARY_DIR}\\gcov\\cobertura.xml"
				${OCC_SOURCES}
				--cover_children
				--
				"${DOS_CMAKE_CTEST_COMMAND}" --output-on-failure -C "${${COVERALLS_PREFIX}COVERALLS_CONFIGURATION}"
			DEPENDS coveralls_prepare
			WORKING_DIRECTORY "${PROJECT_BINARY_DIR}"
			COMMENT "Running all tests (through OpenCppCoverage)..."
			VERBATIM
		)
	else()
		add_custom_target(coveralls_test
			# Run tests and regenerate the counters
			COMMAND ${CMAKE_CTEST_COMMAND} --output-on-failure
			DEPENDS coveralls_prepare
			WORKING_DIRECTORY "${PROJECT_BINARY_DIR}"
			COMMENT "Running all tests..."
			VERBATIM
		)
	endif()

	set(JOIN_DIRS "")
	foreach(DIR_NAME ${${COVERALLS_PREFIX}COVERALLS_DIRS})
		if (JOIN_DIRS)
			set(JOIN_DIRS "${JOIN_DIRS}:")
		endif()
		set(JOIN_DIRS "${JOIN_DIRS}${DIR_NAME}")
	endforeach()

	set(JOIN_IGNORE_FILES)
	foreach(FILE_MASK ${${COVERALLS_PREFIX}COVERALLS_IGNORE_FILES})
		set(JOIN_IGNORE_FILES ${JOIN_IGNORE_FILES} --ignore-file "${FILE_MASK}")
	endforeach()

	message(STATUS "Python3_EXECUTABLE is: ${Python3_EXECUTABLE}")
	if(OCC_EXECUTABLE)
		add_custom_target(coveralls_generate
			# Run python over the output and generate coveralls JSON
			COMMAND ${Python3_EXECUTABLE}
				"${CMAKE_CURRENT_LIST_DIR}/coveralls.py"
				--cobertura
				--git "${GIT_EXECUTABLE}"
				--src_dir "${PROJECT_SOURCE_DIR}"
				--bin_dir "${PROJECT_BINARY_DIR}"
				--int_dir "${PROJECT_BINARY_DIR}/gcov"
				--dirs "${JOIN_DIRS}"
				--out "${${COVERALLS_PREFIX}COVERALLS_FILE}"
				${JOIN_IGNORE_FILES}
			DEPENDS
				coveralls_test
				"${CMAKE_CURRENT_LIST_DIR}/coveralls.py"
			WORKING_DIRECTORY "${PROJECT_BINARY_DIR}/gcov"
			COMMENT "Generating coveralls output..."
		)
	else()
		add_custom_target(coveralls_generate
			# Run gcov over the output and generate coveralls JSON
			COMMAND ${Python3_EXECUTABLE}
				"${CMAKE_CURRENT_LIST_DIR}/coveralls.py"
				--gcov "${GCOV_EXECUTABLE}"
				--git "${GIT_EXECUTABLE}"
				--src_dir "${PROJECT_SOURCE_DIR}"
				--bin_dir "${PROJECT_BINARY_DIR}"
				--int_dir "${PROJECT_BINARY_DIR}/gcov"
				--dirs "${JOIN_DIRS}"
				--out "${${COVERALLS_PREFIX}COVERALLS_FILE}"
				${JOIN_IGNORE_FILES}
			DEPENDS
				coveralls_test
				"${CMAKE_CURRENT_LIST_DIR}/coveralls.py"
			WORKING_DIRECTORY "${PROJECT_BINARY_DIR}/gcov"
			COMMENT "Generating coveralls output..."
		)
	endif()

	if (${COVERALLS_PREFIX}COVERALLS_UPLOAD)
		message(STATUS "${COVERALLS_PREFIX}COVERALLS UPLOAD: ON")

		find_program(CURL_EXECUTABLE curl)

		if (NOT CURL_EXECUTABLE)
			message(FATAL_ERROR "Coveralls: curl not found! Aborting")
		endif()

		add_custom_target(coveralls_upload
			# Upload the JSON to coveralls.
			COMMAND ${CURL_EXECUTABLE} -S -F "json_file=@${${COVERALLS_PREFIX}COVERALLS_FILE}" https://coveralls.io/api/v1/jobs

			DEPENDS coveralls_generate

			WORKING_DIRECTORY ${PROJECT_BINARY_DIR}
			COMMENT "Uploading coveralls output...")
		set_target_properties(coveralls_upload PROPERTIES FOLDER "Coveralls Targets")

		add_custom_target(coveralls DEPENDS coveralls_upload)
	else()
		message(STATUS "${COVERALLS_PREFIX}COVERALLS UPLOAD: OFF")
		add_custom_target(coveralls DEPENDS coveralls_generate)
	endif()

	set_target_properties(coveralls coveralls_test coveralls_generate PROPERTIES FOLDER "Coveralls Targets")
endif()
